"""perception.py — HM3D 씬 안 RGB-D 인식 → point cloud → 인식 SceneGraph (Phase 4).

Track B("인식 기반 Scene Graph")를 실제로 구동하는 모듈:

  RGB-D + segmentation 캡처 (PyBullet, 실제 스캔 씬)
    → depth 역투영 point cloud (V-1 수정된 픽셀↔포인트 매핑)
    → spawn 객체: segmentation buffer GT mask로 분리 (V-2)
    → 지지면 위 클러터: 상면 위 포인트 DBSCAN 클러스터링 (mask 불필요한
      class-agnostic 인식 — HM3D mesh chunk는 semantic 인스턴스와 1:1이
      아니므로 seg buffer로 가구를 분리할 수 없다)
    → 인식 SceneGraph 생성 + semantic GT와 비교 지표

좌표계 주의: PyBullet view matrix는 OpenGL 관례(카메라 -z 전방, +y 위)이고
핀홀 역투영은 CV 관례(+z 전방, +y 아래)다. 세계 좌표 변환 시
GL→CV 플립 diag(1,-1,-1)을 반드시 삽입한다 (기존
vision.rgbd_to_graph.capture_rgbd_from_pybullet에는 이 플립이 없다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pybullet as p

from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface
from vision.rgbd_to_graph import (
    CameraIntrinsics,
    depth_to_pointcloud,
    extract_object_pointclouds,
)

from .semantics import SemanticInstance
from .workspace import HM3DWorkspace, SceneBox

# GL 카메라 좌표 → CV 핀홀 좌표 플립
_GL_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])


@dataclass
class CapturedView:
    """RGB-D + segmentation 캡처 결과."""

    rgb: np.ndarray          # (H, W, 3) uint8
    depth: np.ndarray        # (H, W) float32, 선형 미터
    seg: np.ndarray          # (H, W) int32, body id (-1 = 배경)
    intrinsics: CameraIntrinsics
    extrinsic_cv: np.ndarray  # (4, 4) CV 카메라 → 월드
    eye: list[float]
    target: list[float]


def capture_rgbd_seg(
    cid: int,
    eye: list[float],
    target: list[float],
    width: int = 640,
    height: int = 480,
    fov: float = 60.0,
    near: float = 0.05,
    far: float = 8.0,
) -> CapturedView:
    """지정 시점에서 RGB + 선형 depth + segmentation을 캡처한다."""
    view = p.computeViewMatrix(eye, target, [0, 0, 1], physicsClientId=cid)
    proj = p.computeProjectionMatrixFOV(
        fov=fov, aspect=width / height, nearVal=near, farVal=far,
        physicsClientId=cid,
    )
    _, _, rgba, depth_buf, seg = p.getCameraImage(
        width, height,
        viewMatrix=view,
        projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER,
        physicsClientId=cid,
    )
    rgb = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]
    depth_buf = np.array(depth_buf, dtype=np.float32).reshape(height, width)
    depth = far * near / (far - (far - near) * depth_buf)
    seg = np.array(seg, dtype=np.int32).reshape(height, width)

    intr = CameraIntrinsics.from_pybullet_fov(width, height, fov)
    view_np = np.array(view, dtype=np.float64).reshape(4, 4).T  # column-major
    extrinsic_gl = np.linalg.inv(view_np)          # GL 카메라 → 월드
    extrinsic_cv = extrinsic_gl @ _GL_TO_CV        # CV 카메라 → 월드

    return CapturedView(
        rgb=rgb, depth=depth, seg=seg, intrinsics=intr,
        extrinsic_cv=extrinsic_cv, eye=list(eye), target=list(target),
    )


def view_to_world_pointcloud(view: CapturedView, depth_max: float = 6.0):
    """캡처 → (월드 point cloud, valid mask). V-1 매핑 유지."""
    pcd_cam, valid = depth_to_pointcloud(
        view.depth, view.intrinsics, depth_max=depth_max, return_valid_mask=True
    )
    pcd_world = pcd_cam.transform(view.extrinsic_cv)
    return pcd_world, valid


def masks_from_segmentation(
    seg: np.ndarray, body_ids: dict[str, int]
) -> dict[str, np.ndarray]:
    """segmentation buffer → {obj_id: (H, W) bool mask} (V-2, GT mask)."""
    return {obj_id: seg == bid for obj_id, bid in body_ids.items()}


@dataclass
class DetectedObject:
    """인식된 객체 (spawn 객체 또는 클러터 클러스터)."""

    det_id: str
    center: np.ndarray
    size: np.ndarray
    n_points: int
    source: str  # "seg_mask" | "cluster"


def detect_spawned_objects(
    view: CapturedView,
    pcd_world,
    valid: np.ndarray,
    body_map: dict[str, int],
) -> list[DetectedObject]:
    """seg mask 기반 spawn 객체 인식 → point cloud AABB."""
    mask_map = masks_from_segmentation(view.seg, body_map)
    obj_pcds = extract_object_pointclouds(
        pcd_world, mask_map, view.depth.shape, valid_mask=valid
    )
    result = []
    for obj_id, pcd in obj_pcds.items():
        pts = np.asarray(pcd.points)
        if len(pts) < 15:
            continue
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        result.append(DetectedObject(
            det_id=obj_id,
            center=(lo + hi) / 2.0,
            size=hi - lo,
            n_points=len(pts),
            source="seg_mask",
        ))
    return result


def detect_surface_clutter(
    pcd_world,
    valid: np.ndarray,
    seg: np.ndarray,
    surface: SceneBox,
    exclude_body_ids: list[int],
    eps: float = 0.04,
    min_points: int = 30,
    z_band: tuple[float, float] = (0.015, 0.45),
) -> list[DetectedObject]:
    """지지면 위 클러터를 DBSCAN으로 인식한다 (class-agnostic).

    상면 z + z_band 높이의 포인트 중 spawn 객체(seg 제외)가 아닌 것을
    클러스터링 → 클러스터별 AABB.
    """
    import open3d as o3d

    pts = np.asarray(pcd_world.points)
    seg_flat = seg.flatten()[valid.flatten()]

    top = surface.top_z
    lo, hi = surface.bbox_min, surface.bbox_max
    m = 0.05
    sel = (
        (pts[:, 2] > top + z_band[0]) & (pts[:, 2] < top + z_band[1])
        & (pts[:, 0] > lo[0] - m) & (pts[:, 0] < hi[0] + m)
        & (pts[:, 1] > lo[1] - m) & (pts[:, 1] < hi[1] + m)
        & ~np.isin(seg_flat, exclude_body_ids)
    )
    sel_pts = pts[sel]
    if len(sel_pts) < min_points:
        return []

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(sel_pts)
    labels = np.asarray(pcd.cluster_dbscan(eps=eps, min_points=min_points))

    result = []
    for k in range(labels.max() + 1):
        cpts = sel_pts[labels == k]
        clo, chi = cpts.min(axis=0), cpts.max(axis=0)
        result.append(DetectedObject(
            det_id=f"clutter_{k:02d}",
            center=(clo + chi) / 2.0,
            size=chi - clo,
            n_points=len(cpts),
            source="cluster",
        ))
    return result


def estimate_surface_height(
    pcd_world,
    surface: SceneBox,
) -> Optional[float]:
    """상면 높이를 point cloud에서 실측한다 (semantic GT와 독립 검증용)."""
    pts = np.asarray(pcd_world.points)
    lo, hi = surface.bbox_min, surface.bbox_max
    sel = (
        (pts[:, 0] > lo[0]) & (pts[:, 0] < hi[0])
        & (pts[:, 1] > lo[1]) & (pts[:, 1] < hi[1])
        & (pts[:, 2] > surface.top_z - 0.15) & (pts[:, 2] < surface.top_z + 0.05)
    )
    band = pts[sel][:, 2]
    if len(band) < 50:
        return None
    # 상면은 z 히스토그램 최빈 구간
    bins = np.arange(band.min(), band.max() + 0.005, 0.005)
    counts, edges = np.histogram(band, bins=bins)
    return float(edges[int(np.argmax(counts))] + 0.0025)


def build_perceived_scene_graph(
    scene_id: str,
    surface: SceneBox,
    surface_height_measured: Optional[float],
    detections: list[DetectedObject],
    role_map: dict[str, str],
) -> SceneGraph:
    """인식 결과 → SceneGraph (source=hm3d_rgbd).

    role_map: {det_id: Role} — spawn 객체의 역할 (target/obstacle/destination).
              클러터 클러스터는 OBSTACLE.
    """
    height = (
        surface_height_measured
        if surface_height_measured is not None
        else surface.top_z
    )
    surf = SupportSurface(
        id=f"perceived_{surface.id}",
        type="plane",
        height=height,
        bounds={
            "x": [float(surface.bbox_min[0]), float(surface.bbox_max[0])],
            "y": [float(surface.bbox_min[1]), float(surface.bbox_max[1])],
        },
    )
    objects = []
    for det in detections:
        role = role_map.get(det.det_id, Role.OBSTACLE)
        objects.append(ObjectNode(
            id=det.det_id,
            role=role,
            position=det.center.tolist(),
            size=np.maximum(det.size, 0.01).tolist(),
            movable=(det.source == "seg_mask"),
            shape="block",
            extra={"n_points": det.n_points, "det_source": det.source},
        ))
    return SceneGraph(
        scene_id=scene_id,
        support_surfaces=[surf],
        objects=objects,
        meta={"source": "hm3d_rgbd"},
    )


# ---------------------------------------------------------------------------
# GT 비교 평가
# ---------------------------------------------------------------------------

@dataclass
class PerceptionReport:
    """인식 vs GT 비교 지표."""

    spawned_errors: dict[str, dict] = field(default_factory=dict)
    surface_height_error_m: Optional[float] = None
    clutter_matched: list[dict] = field(default_factory=list)
    clutter_missed: list[dict] = field(default_factory=list)
    clutter_spurious: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "spawned_errors": self.spawned_errors,
            "surface_height_error_m": self.surface_height_error_m,
            "clutter_matched": self.clutter_matched,
            "clutter_missed": self.clutter_missed,
            "clutter_spurious": self.clutter_spurious,
        }


def compare_with_gt(
    workspace: HM3DWorkspace,
    detections: list[DetectedObject],
    surface_height_measured: Optional[float],
    gt_clutter: list[SemanticInstance],
    match_dist: float = 0.30,
) -> PerceptionReport:
    """인식 결과를 GT(spawn 노드 + semantic 인스턴스)와 비교한다.

    Args:
        gt_clutter: 지지면 위 semantic 인스턴스 (상면 위 z 겹침 기준으로
                    호출자가 필터한 목록).
    """
    report = PerceptionReport()

    # 1) spawn 객체: 위치/크기 오차
    det_by_id = {d.det_id: d for d in detections if d.source == "seg_mask"}
    for node in workspace.sg.objects:
        if node.extra.get("hm3d_context"):
            continue
        det = det_by_id.get(node.id)
        if det is None:
            report.spawned_errors[node.id] = {"detected": False}
            continue
        pos_err = float(np.linalg.norm(det.center - np.array(node.position)))
        size_err = float(
            np.abs(det.size - np.array(node.size)).max()
        )
        report.spawned_errors[node.id] = {
            "detected": True,
            "position_error_m": round(pos_err, 4),
            "size_error_max_m": round(size_err, 4),
            "n_points": det.n_points,
        }

    # 2) 지지면 높이 실측 오차
    if surface_height_measured is not None:
        report.surface_height_error_m = round(
            abs(surface_height_measured - workspace.surface.top_z), 4
        )

    # 3) 클러터 매칭 (수평 중심 거리)
    clusters = [d for d in detections if d.source == "cluster"]
    used = set()
    for inst in gt_clutter:
        best, best_d = None, match_dist
        for i, det in enumerate(clusters):
            if i in used:
                continue
            d = float(np.linalg.norm(det.center[:2] - inst.center[:2]))
            if d < best_d:
                best, best_d = i, d
        entry = {
            "gt": f"#{inst.instance_id} {inst.category}",
            "gt_center": np.round(inst.center, 3).tolist(),
        }
        if best is None:
            report.clutter_missed.append(entry)
        else:
            used.add(best)
            det = clusters[best]
            entry.update({
                "det": det.det_id,
                "center_error_m": round(best_d, 4),
                "size_error_max_m": round(
                    float(np.abs(det.size - inst.size).max()), 4
                ),
            })
            report.clutter_matched.append(entry)

    for i, det in enumerate(clusters):
        if i not in used:
            report.clutter_spurious.append({
                "det": det.det_id,
                "center": np.round(det.center, 3).tolist(),
                "n_points": det.n_points,
            })

    return report


def gt_clutter_on_surface(
    instances: list[SemanticInstance],
    surface: SceneBox,
    z_band: tuple[float, float] = (0.015, 0.45),
) -> list[SemanticInstance]:
    """지지면 위에 '놓인' semantic 인스턴스 (클러터 GT).

    벽/커튼처럼 바닥부터 천장까지 이어지는 인스턴스는 xy가 겹쳐도
    상면에 놓인 물체가 아니므로, bbox 바닥이 상면 근처인 것만 취한다.

    surface는 이미 지지면 자체를 선택한 SceneBox(workspace.py 변환 결과)라
    instances(HM3D 원본 정밀 인스턴스 목록) 중 자기 자신은 xy+높이 bbox가
    거의 일치하는 항목으로 식별해 제외한다 (두 타입 간 공유 ID 체계 없음).
    """
    top = surface.top_z
    lo, hi = surface.bbox_min, surface.bbox_max
    result = []
    for inst in instances:
        if (np.allclose(inst.bbox_min[:2], lo[:2], atol=0.02)
                and np.allclose(inst.bbox_max[:2], hi[:2], atol=0.02)
                and abs(inst.top_z - top) < 0.02):
            continue  # 지지면 자기 자신
        c = inst.center
        if not (lo[0] - 0.05 < c[0] < hi[0] + 0.05
                and lo[1] - 0.05 < c[1] < hi[1] + 0.05):
            continue
        # 상면에 놓임: bbox 바닥이 상면 ±(-5cm ~ +25cm)
        if not (top - 0.05 <= inst.bbox_min[2] <= top + 0.25):
            continue
        # 상면 z_band와 z 범위가 겹침
        if inst.bbox_max[2] < top + z_band[0] or inst.bbox_min[2] > top + z_band[1]:
            continue
        result.append(inst)
    return result


# ---------------------------------------------------------------------------
# 시각화: bbox를 이미지에 투영
# ---------------------------------------------------------------------------

def project_bbox_to_image(
    center: np.ndarray,
    size: np.ndarray,
    view: CapturedView,
) -> Optional[tuple[int, int, int, int]]:
    """월드 AABB → 이미지 2D bbox (u_min, v_min, u_max, v_max)."""
    half = np.asarray(size) / 2.0
    corners = np.array([
        center + half * np.array([sx, sy, sz])
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ])
    world_to_cv = np.linalg.inv(view.extrinsic_cv)
    cam = corners @ world_to_cv[:3, :3].T + world_to_cv[:3, 3]
    if np.any(cam[:, 2] <= 0.01):
        return None
    intr = view.intrinsics
    u = intr.fx * cam[:, 0] / cam[:, 2] + intr.cx
    v = intr.fy * cam[:, 1] / cam[:, 2] + intr.cy
    h, w = view.depth.shape
    u_min, u_max = int(max(0, u.min())), int(min(w - 1, u.max()))
    v_min, v_max = int(max(0, v.min())), int(min(h - 1, v.max()))
    if u_min >= u_max or v_min >= v_max:
        return None
    return u_min, v_min, u_max, v_max
