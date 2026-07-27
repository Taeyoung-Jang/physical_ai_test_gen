"""semantics.py — HM3D semantic annotation → 인스턴스 bbox → 실측 SceneGraph.

HM3D semantic 데이터 구조:
  - <scene>.semantic.txt : "id,HEXCOLOR,\"category\",region" 팔레트 (헤더 1줄)
  - <scene>.semantic.glb : 시각 GLB와 동일 좌표계의 mesh. 인스턴스 ID가
    **texture 색**으로 인코딩됨 (vertex color 아님).

추출 방법 (00800에서 face-centroid 샘플링 정확 매칭 91.9% 검증):
  face의 UV 중심에서 texture를 nearest 샘플링 → 팔레트 색과 매칭 → 인스턴스 ID.
  경계 픽셀로 매칭 실패한 face는 버린다 (bbox 계산에는 영향 미미).

출력 SceneGraph는 Track A 스키마와 호환된다. 벽/바닥/천장 등 구조물은
ObjectNode에서 제외하고(충돌은 static mesh가 담당) meta에 개수만 기록한다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface

# 집 구조물 — SceneGraph ObjectNode에서 제외
STRUCTURAL_CATEGORIES = {
    "wall", "floor", "ceiling", "door", "door frame", "doorframe", "window",
    "window frame", "stairs", "stair", "railing", "beam", "column", "arch",
    "unknown", "ceiling lamp", "chandelier", "vent", "duct",
}

# 지지면(작업면) 후보 카테고리
SUPPORT_CATEGORIES = {
    "table", "desk", "counter", "countertop", "kitchen counter", "nightstand",
    "coffee table", "dining table", "side table", "dresser", "cabinet",
    "kitchen island", "shelf", "kitchen shelf", "bench",
}

# 로봇 작업 가능 지지면 높이 범위 (m)
SUPPORT_HEIGHT_RANGE = (0.35, 1.10)
# 지지면 최소 상면 면적 (m²)
SUPPORT_MIN_AREA = 0.08


@dataclass
class SemanticInstance:
    """semantic annotation에서 추출된 객체 인스턴스."""

    instance_id: int
    category: str
    region: int
    rgb: tuple[int, int, int]
    n_faces: int = 0
    bbox_min: Optional[np.ndarray] = None  # PyBullet 월드 좌표 (offset 적용)
    bbox_max: Optional[np.ndarray] = None

    @property
    def center(self) -> np.ndarray:
        return (self.bbox_min + self.bbox_max) / 2.0

    @property
    def size(self) -> np.ndarray:
        return self.bbox_max - self.bbox_min

    @property
    def top_z(self) -> float:
        return float(self.bbox_max[2])

    @property
    def footprint_area(self) -> float:
        s = self.size
        return float(s[0] * s[1])


def parse_semantic_txt(path: str | Path) -> dict[tuple[int, int, int], SemanticInstance]:
    """semantic.txt → {rgb: SemanticInstance} 팔레트."""
    palette: dict[tuple[int, int, int], SemanticInstance] = {}
    lines = Path(path).read_text().splitlines()
    for line in lines[1:]:  # 헤더 스킵
        m = re.match(r'(\d+),([0-9A-Fa-f]{6}),"(.+)",(\d+)', line)
        if not m:
            continue
        hexc = m.group(2)
        rgb = (int(hexc[0:2], 16), int(hexc[2:4], 16), int(hexc[4:6], 16))
        palette[rgb] = SemanticInstance(
            instance_id=int(m.group(1)),
            category=m.group(3).strip().lower(),
            region=int(m.group(4)),
            rgb=rgb,
        )
    return palette


def extract_instances(
    semantic_glb_path: str | Path,
    semantic_txt_path: str | Path,
    offset: Optional[list[float]] = None,
    min_faces: int = 6,
    min_size: float = 0.03,
) -> list[SemanticInstance]:
    """semantic.glb에서 인스턴스별 AABB를 추출한다.

    Args:
        offset: loader의 ConvertedScene.offset — 시각 씬과 동일한 PyBullet
                월드 좌표(중심 xy=0, 바닥 z≈0)로 정렬하기 위해 적용.
        min_faces: 이보다 face가 적은 인스턴스는 노이즈로 간주하고 버린다.
        min_size: 최대 변 길이가 이보다 작은 인스턴스는 버린다.
    """
    try:
        import trimesh
    except ImportError as e:
        raise ImportError(
            "trimesh가 필요합니다: uv sync --extra hm3d"
        ) from e

    palette = parse_semantic_txt(semantic_txt_path)
    by_id = {inst.instance_id: inst for inst in palette.values()}

    scene = trimesh.load(str(semantic_glb_path))
    if not hasattr(scene, "geometry"):
        scene = trimesh.Scene(scene)

    off = np.array(offset if offset is not None else [0.0, 0.0, 0.0])

    # rgb → instance_id 벡터 매핑 테이블 (24-bit 키)
    keys = np.array([r << 16 | g << 8 | b for (r, g, b) in palette], dtype=np.int64)
    vals = np.array([palette[k].instance_id for k in palette], dtype=np.int64)
    order = np.argsort(keys)
    keys_sorted, vals_sorted = keys[order], vals[order]

    bbox_min: dict[int, np.ndarray] = {}
    bbox_max: dict[int, np.ndarray] = {}
    n_faces: dict[int, int] = defaultdict(int)

    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node_name]
        g = scene.geometry[geom_name]
        visual = getattr(g, "visual", None)
        if visual is None or getattr(visual, "uv", None) is None:
            continue
        material = getattr(visual, "material", None)
        tex = getattr(material, "baseColorTexture", None) if material else None
        if tex is None or g.faces.shape[0] == 0:
            continue

        img = np.asarray(tex)[:, :, :3]
        h, w = img.shape[:2]

        # face UV 중심 → nearest 픽셀 색
        fuv = visual.uv[g.faces].mean(axis=1)
        px = np.clip((fuv[:, 0] * w).astype(np.int64), 0, w - 1)
        py = np.clip(((1.0 - fuv[:, 1]) * h).astype(np.int64), 0, h - 1)
        cols = img[py, px].astype(np.int64)
        col_keys = cols[:, 0] << 16 | cols[:, 1] << 8 | cols[:, 2]

        # 팔레트 정확 매칭 (이진 탐색)
        pos = np.searchsorted(keys_sorted, col_keys)
        pos = np.clip(pos, 0, len(keys_sorted) - 1)
        hit = keys_sorted[pos] == col_keys
        face_iids = np.where(hit, vals_sorted[pos], -1)

        # 월드 좌표 변환
        verts = g.vertices @ transform[:3, :3].T + transform[:3, 3]

        for iid in np.unique(face_iids):
            if iid < 0:
                continue
            mask = face_iids == iid
            pts = verts[g.faces[mask].ravel()]
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            if iid in bbox_min:
                bbox_min[iid] = np.minimum(bbox_min[iid], lo)
                bbox_max[iid] = np.maximum(bbox_max[iid], hi)
            else:
                bbox_min[iid], bbox_max[iid] = lo, hi
            n_faces[iid] += int(mask.sum())

    instances: list[SemanticInstance] = []
    for iid, lo in bbox_min.items():
        if iid not in by_id or n_faces[iid] < min_faces:
            continue
        inst = by_id[iid]
        inst.bbox_min = lo + off
        inst.bbox_max = bbox_max[iid] + off
        inst.n_faces = n_faces[iid]
        if float(inst.size.max()) < min_size:
            continue
        instances.append(inst)

    instances.sort(key=lambda x: x.instance_id)
    return instances


def select_support_surfaces(
    instances: list[SemanticInstance],
    height_range: tuple[float, float] = SUPPORT_HEIGHT_RANGE,
    min_area: float = SUPPORT_MIN_AREA,
) -> list[SemanticInstance]:
    """로봇 작업 가능한 지지면 후보 (카테고리 + 상면 높이 + 면적 필터)."""
    result = []
    for inst in instances:
        if inst.category not in SUPPORT_CATEGORIES:
            continue
        if not (height_range[0] <= inst.top_z <= height_range[1]):
            continue
        if inst.footprint_area < min_area:
            continue
        result.append(inst)
    result.sort(key=lambda x: -x.footprint_area)
    return result


def build_scene_graph(
    instances: list[SemanticInstance],
    scene_id: str,
    include_structural: bool = False,
) -> SceneGraph:
    """인스턴스 목록 → Track A 호환 SceneGraph.

    모든 인스턴스는 스캔에 융합된 static geometry이므로 movable=False인
    OBSTACLE로 넣는다 (target/destination은 Phase 3에서 spawner가 추가).
    """
    objects: list[ObjectNode] = []
    structural_count: dict[str, int] = defaultdict(int)

    for inst in instances:
        if inst.category in STRUCTURAL_CATEGORIES and not include_structural:
            structural_count[inst.category] += 1
            continue
        objects.append(
            ObjectNode(
                id=f"hm3d_{inst.instance_id:04d}_{inst.category.replace(' ', '_')}",
                role=Role.OBSTACLE,
                position=inst.center.tolist(),
                size=inst.size.tolist(),
                movable=False,
                shape="mesh",
                extra={
                    "category": inst.category,
                    "region": inst.region,
                    "hm3d_instance_id": inst.instance_id,
                    "n_faces": inst.n_faces,
                },
            )
        )

    supports = select_support_surfaces(instances)
    support_surfaces = [
        SupportSurface(
            id=f"hm3d_{s.instance_id:04d}_{s.category.replace(' ', '_')}",
            type="plane",
            height=s.top_z,
            bounds={
                "x": [float(s.bbox_min[0]), float(s.bbox_max[0])],
                "y": [float(s.bbox_min[1]), float(s.bbox_max[1])],
            },
        )
        for s in supports
    ]

    return SceneGraph(
        scene_id=scene_id,
        support_surfaces=support_surfaces,
        objects=objects,
        meta={
            "source": "hm3d_semantic",
            "n_instances": len(instances),
            "n_objects": len(objects),
            "n_support_surfaces": len(support_surfaces),
            "structural_counts": dict(structural_count),
        },
    )
