"""loader.py — HM3D GLB → OBJ 변환 캐시 + PyBullet static 로드.

PyBullet은 GLB를 읽지 못하므로 trimesh로 OBJ(+MTL/텍스처)로 변환해 캐시한다.

변환 전략:
  - GLB 내부 geometry(텍스처 아틀라스 조각, 씬당 ~200개)를 **chunk 단위로 개별
    디렉터리에** 내보낸다. chunk마다 재질이 하나라서 PyBullet(tinyobjloader)의
    다중 재질 OBJ 처리 문제와 MTL/텍스처 파일명 충돌을 모두 피한다.
  - glTF는 Y-up이지만 trimesh 로드 시 Z-up으로 변환된다 (00800 씬에서 확인).
  - 전체 bounds를 계산해 "바닥 z=0, 씬 중심 xy=(0,0)"이 되는 offset을 meta에
    저장하고, PyBullet 로드 시 basePosition으로 적용한다.

로드 전략:
  - chunk마다 mass=0 static multibody 생성.
  - collision은 GEOM_FORCE_CONCAVE_TRIMESH (static 전용 concave mesh).
  - oracle 거리 쿼리에서 배경 chunk를 구분할 수 있도록 body_id 목록을 반환한다.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pybullet as p

DEFAULT_CACHE_DIR = "data/hm3d_cache"


@dataclass
class ConvertedScene:
    """OBJ 변환 캐시 메타."""

    scene_dir: str
    cache_dir: Path
    chunk_objs: list[Path]
    bounds_raw: list[list[float]]  # 변환 전 [min, max] (trimesh 좌표계)
    offset: list[float]  # PyBullet 배치 offset (중심 xy=0, 바닥 z=0)
    n_faces: int

    @property
    def extent(self) -> np.ndarray:
        b = np.array(self.bounds_raw)
        return b[1] - b[0]


def convert_glb_to_obj(
    glb_path: str | Path,
    scene_dir: str,
    cache_root: str | Path = DEFAULT_CACHE_DIR,
    force: bool = False,
) -> ConvertedScene:
    """GLB를 chunk 단위 OBJ로 변환한다. 캐시가 있으면 재사용."""
    cache_dir = Path(cache_root) / scene_dir
    meta_path = cache_dir / "meta.json"

    if meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        chunk_objs = [cache_dir / c for c in meta["chunks"]]
        if all(c.exists() for c in chunk_objs):
            return ConvertedScene(
                scene_dir=scene_dir,
                cache_dir=cache_dir,
                chunk_objs=chunk_objs,
                bounds_raw=meta["bounds_raw"],
                offset=meta["offset"],
                n_faces=meta["n_faces"],
            )

    try:
        import trimesh
    except ImportError as e:
        raise ImportError(
            "trimesh가 필요합니다: uv sync --extra hm3d (또는 --extra gen3d)"
        ) from e

    t0 = time.time()
    scene = trimesh.load(str(glb_path))
    if not hasattr(scene, "geometry"):
        # 단일 mesh인 경우 Scene으로 감싼다
        scene = trimesh.Scene(scene)

    cache_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[str] = []
    n_faces = 0
    bounds_min = np.full(3, np.inf)
    bounds_max = np.full(3, -np.inf)

    idx = 0
    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node_name]
        mesh = scene.geometry[geom_name]
        if mesh.faces.shape[0] == 0:
            continue
        mesh = mesh.copy()
        mesh.apply_transform(transform)

        chunk_name = f"chunk_{idx:04d}"
        chunk_dir = cache_dir / chunk_name
        chunk_dir.mkdir(exist_ok=True)
        obj_path = chunk_dir / "model.obj"
        mesh.export(str(obj_path))

        chunks.append(f"{chunk_name}/model.obj")
        n_faces += int(mesh.faces.shape[0])
        bounds_min = np.minimum(bounds_min, mesh.bounds[0])
        bounds_max = np.maximum(bounds_max, mesh.bounds[1])
        idx += 1

    if not chunks:
        raise ValueError(f"GLB에 geometry가 없음: {glb_path}")

    center = (bounds_min + bounds_max) / 2.0
    # 씬 중심 xy → (0,0), 바닥 → z=0
    offset = [-float(center[0]), -float(center[1]), -float(bounds_min[2])]

    meta = {
        "scene_dir": scene_dir,
        "source_glb": str(glb_path),
        "chunks": chunks,
        "bounds_raw": [bounds_min.tolist(), bounds_max.tolist()],
        "offset": offset,
        "n_faces": n_faces,
        "convert_seconds": round(time.time() - t0, 1),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    return ConvertedScene(
        scene_dir=scene_dir,
        cache_dir=cache_dir,
        chunk_objs=[cache_dir / c for c in chunks],
        bounds_raw=meta["bounds_raw"],
        offset=offset,
        n_faces=n_faces,
    )


def load_hm3d_static(
    converted: ConvertedScene,
    client_id: int,
    collision: bool = True,
) -> list[int]:
    """변환된 chunk OBJ들을 PyBullet static body로 로드한다.

    Returns:
        body_ids: 생성된 static body id 목록 (배경 chunk 구분용)
    """
    base_pos = converted.offset
    body_ids: list[int] = []
    for obj_path in converted.chunk_objs:
        vis_id = p.createVisualShape(
            p.GEOM_MESH,
            fileName=str(obj_path),
            meshScale=[1, 1, 1],
            physicsClientId=client_id,
        )
        col_id = -1
        if collision:
            col_id = p.createCollisionShape(
                p.GEOM_MESH,
                fileName=str(obj_path),
                meshScale=[1, 1, 1],
                flags=p.GEOM_FORCE_CONCAVE_TRIMESH,
                physicsClientId=client_id,
            )
        body_id = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=col_id,
            baseVisualShapeIndex=vis_id,
            basePosition=base_pos,
            physicsClientId=client_id,
        )
        body_ids.append(body_id)
    return body_ids


def scene_extent_pybullet(converted: ConvertedScene) -> tuple[np.ndarray, np.ndarray]:
    """PyBullet 좌표계(offset 적용 후)에서의 [min, max] bounds."""
    b = np.array(converted.bounds_raw)
    off = np.array(converted.offset)
    return b[0] + off, b[1] + off


def find_free_floor_spots(
    client_id: int,
    lo: np.ndarray,
    hi: np.ndarray,
    grid: float = 0.30,
    cast_start_z: float = 1.9,
    floor_max_z: float = 0.8,
    floor_tol: float = 0.06,
    clearance_h: float = 1.6,
    margin: float = 0.5,
) -> tuple[list[tuple[float, float]], float]:
    """raycast로 1층의 '빈 바닥' 지점을 찾는다 (로봇/카메라 배치용).

    스캔에는 지붕/천장이 포함되므로 ray를 씬 꼭대기가 아니라 1층 천장 아래
    (cast_start_z)에서 아래로 쏜다. 바닥 높이도 z=0으로 가정하지 않고
    hit 높이 히스토그램의 최빈값으로 추정한다 (스캔 최저점 outlier 대비).

    Returns:
        (spots, floor_z):
          spots — (x, y) 목록, 씬 중심에서 가까운 순.
          floor_z — 추정 바닥 높이 (spots가 비면 0.0).
        collision shape 없이 로드된 씬에서는 빈 목록이 나온다.
    """
    xs = np.arange(lo[0] + margin, hi[0] - margin, grid)
    ys = np.arange(lo[1] + margin, hi[1] - margin, grid)
    if len(xs) == 0 or len(ys) == 0:
        return [], 0.0
    gx, gy = np.meshgrid(xs, ys)
    pts = np.stack([gx.ravel(), gy.ravel()], axis=-1)

    # 1) 아래로 ray: 각 (x,y)의 첫 hit 높이 수집
    hit_z = np.full(len(pts), np.nan)
    batch = 2048
    for i in range(0, len(pts), batch):
        chunk = pts[i : i + batch]
        starts = [[x, y, cast_start_z] for x, y in chunk]
        ends = [[x, y, float(lo[2]) - 0.5] for x, y in chunk]
        hits = p.rayTestBatch(starts, ends, physicsClientId=client_id)
        for j, h in enumerate(hits):
            if h[0] >= 0:
                hit_z[i + j] = h[3][2]

    # 2) 바닥 높이 추정: floor_max_z 이하 hit들의 최빈 구간 (2cm bin)
    low_hits = hit_z[~np.isnan(hit_z)]
    low_hits = low_hits[low_hits < floor_max_z]
    if len(low_hits) == 0:
        return [], 0.0
    bins = np.arange(low_hits.min(), low_hits.max() + 0.02, 0.02)
    counts, edges = np.histogram(low_hits, bins=bins)
    floor_z = float(edges[int(np.argmax(counts))] + 0.01)

    # 3) 바닥 hit 지점만 clearance 검사 (바닥 위 0.1~clearance_h 비어 있어야)
    floor_idx = np.where(np.abs(hit_z - floor_z) < floor_tol)[0]
    spots: list[tuple[float, float]] = []
    for i in range(0, len(floor_idx), batch):
        idx_chunk = floor_idx[i : i + batch]
        c_starts = [[pts[j][0], pts[j][1], floor_z + 0.10] for j in idx_chunk]
        c_ends = [[pts[j][0], pts[j][1], floor_z + clearance_h] for j in idx_chunk]
        c_hits = p.rayTestBatch(c_starts, c_ends, physicsClientId=client_id)
        for j, h in zip(idx_chunk, c_hits):
            if h[0] < 0:  # 위로 막힌 것 없음 → 빈 바닥
                spots.append((float(pts[j][0]), float(pts[j][1])))

    center = (lo[:2] + hi[:2]) / 2.0
    spots.sort(key=lambda s: (s[0] - center[0]) ** 2 + (s[1] - center[1]) ** 2)
    return spots, floor_z


def pick_camera_eye(
    client_id: int,
    spots: list[tuple[float, float]],
    target: list[float],
    floor_z: float,
    eye_height: float = 1.4,
    d_min: float = 1.2,
    d_max: float = 3.5,
) -> Optional[list[float]]:
    """target이 가려지지 않고 보이는 카메라 eye 위치를 빈 바닥 지점에서 고른다.

    벽/가구를 관통하는 orbit 카메라 대신, 실제 빈 공간에 서서 바라보는
    시점을 만든다. eye→target ray가 target 근처(fraction 0.85+)까지
    도달하면 시야 확보로 판정한다.

    Returns:
        [x, y, z] eye 위치. 적합한 지점이 없으면 None.
    """
    tx, ty = target[0], target[1]
    candidates = []
    for x, y in spots:
        d = math.hypot(x - tx, y - ty)
        if d_min <= d <= d_max:
            candidates.append((d, x, y))
    candidates.sort()

    for _, x, y in candidates:
        eye = [x, y, floor_z + eye_height]
        hit = p.rayTest(eye, target, physicsClientId=client_id)[0]
        if hit[0] < 0 or hit[2] > 0.85:
            return eye
    return None
