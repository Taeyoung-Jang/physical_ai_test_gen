"""rgbd_to_graph.py — Track B: RGB-D 인식 → SceneGraph 변환.

처리 흐름:
  PyBullet camera RGB-D (또는 실제 카메라)
  → depth to point cloud (Open3D)
  → object mask 적용 (ground-truth body_map 또는 외부 segmentation)
  → object point cloud 추출
  → 3D oriented bounding box 계산
  → support plane 추정 (RANSAC 평면 피팅)
  → SceneGraph 생성 (Track A와 동일 스키마)
  → perception_margin 실측값 포함

출력 SceneGraph는 Track A (procedural generation) 스키마와 완전히 호환된다.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import open3d as o3d

from scene_graph import ObjectNode, Relation, Role, SceneGraph, SupportSurface

# ---------------------------------------------------------------------------
# 카메라 내부 파라미터
# ---------------------------------------------------------------------------

class CameraIntrinsics:
    """핀홀 카메라 내부 파라미터."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fx: float = 525.0,
        fy: float = 525.0,
        cx: Optional[float] = None,
        cy: Optional[float] = None,
    ):
        self.width = width
        self.height = height
        self.fx = fx
        self.fy = fy
        self.cx = cx if cx is not None else width / 2.0
        self.cy = cy if cy is not None else height / 2.0

    def to_o3d(self) -> o3d.camera.PinholeCameraIntrinsic:
        return o3d.camera.PinholeCameraIntrinsic(
            self.width, self.height, self.fx, self.fy, self.cx, self.cy
        )

    @classmethod
    def from_pybullet_fov(cls, width: int, height: int, fov_deg: float = 60.0):
        """PyBullet 프로젝션 행렬 FOV에서 내부 파라미터를 계산한다."""
        fx = (width / 2.0) / math.tan(math.radians(fov_deg / 2.0))
        fy = fx
        return cls(width, height, fx, fy)


# ---------------------------------------------------------------------------
# RGB-D → 포인트 클라우드
# ---------------------------------------------------------------------------

def depth_to_pointcloud(
    depth_image: np.ndarray,
    intrinsics: CameraIntrinsics,
    depth_scale: float = 1.0,
    depth_max: float = 3.0,
    return_valid_mask: bool = False,
):
    """Depth map (HxW float32) → Open3D PointCloud (camera 좌표계).

    Args:
        depth_image: (H, W) float32, 미터 단위. PyBullet DIRECT mode에서는
                     getDepthPixelFromDepthBuffer로 선형화해서 전달해야 한다.
        intrinsics: 카메라 내부 파라미터.
        depth_scale: depth → 미터 변환 스케일 (1.0이면 이미 미터).
        depth_max: 이 거리 초과 포인트 필터링.
        return_valid_mask: True면 (pcd, valid) 튜플 반환. valid는 (H, W) bool
                     — 포인트 i는 valid 픽셀을 row-major 순회한 i번째 픽셀에
                     대응한다 (extract_object_pointclouds의 픽셀↔포인트 매핑용).
    """
    h, w = depth_image.shape
    u_coords, v_coords = np.meshgrid(np.arange(w), np.arange(h))
    valid = (depth_image > 0) & (depth_image < depth_max)

    z = depth_image[valid] * depth_scale
    x = (u_coords[valid] - intrinsics.cx) * z / intrinsics.fx
    y = (v_coords[valid] - intrinsics.cy) * z / intrinsics.fy

    points = np.stack([x, y, z], axis=-1).astype(np.float64)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    if return_valid_mask:
        return pcd, valid
    return pcd


def transform_pointcloud(
    pcd: o3d.geometry.PointCloud,
    extrinsic: np.ndarray,
) -> o3d.geometry.PointCloud:
    """카메라 → 월드 좌표계 변환. extrinsic: 4×4 행렬."""
    pcd_world = o3d.geometry.PointCloud(pcd)
    pcd_world.transform(extrinsic)
    return pcd_world


# ---------------------------------------------------------------------------
# Support Plane 추정 (RANSAC)
# ---------------------------------------------------------------------------

def estimate_support_plane(
    pcd: o3d.geometry.PointCloud,
    distance_threshold: float = 0.02,
    ransac_n: int = 3,
    num_iterations: int = 1000,
) -> tuple[np.ndarray, float]:
    """RANSAC으로 지지 평면(테이블 면)을 추정한다.

    Returns:
        plane_model: [a, b, c, d] (ax+by+cz+d=0)
        plane_z: 평면의 Z 좌표 (평면이 수평일 때 ≈ 테이블 높이)
    """
    plane_model, inliers = pcd.segment_plane(
        distance_threshold=distance_threshold,
        ransac_n=ransac_n,
        num_iterations=num_iterations,
    )
    a, b, c, d = plane_model
    # 평면 법선이 +Z에 가까운지 확인 (테이블 수평면)
    normal = np.array([a, b, c])
    if np.dot(normal, [0, 0, 1]) < 0:
        normal = -normal
        d = -d

    # 평면과 원점 사이 거리로 Z 추정 (법선이 [0,0,1]인 경우)
    plane_z = float(-d / (c + 1e-9)) if abs(c) > 0.3 else 0.0
    return plane_model, plane_z


# ---------------------------------------------------------------------------
# 객체별 포인트 클라우드 → 3D Bounding Box
# ---------------------------------------------------------------------------

def extract_object_pointclouds(
    pcd_world: o3d.geometry.PointCloud,
    mask_map: dict[str, np.ndarray],
    image_shape: tuple[int, int],
    valid_mask: Optional[np.ndarray] = None,
) -> dict[str, o3d.geometry.PointCloud]:
    """픽셀 마스크(H×W bool)를 이용해 객체별 포인트 클라우드를 추출한다.

    pcd_world는 valid 픽셀에서만 생성된 포인트를 담고 있으므로,
    픽셀 → 포인트 역매핑 테이블(pixel_to_point)을 만들어 색인한다.

    Args:
        pcd_world: 전체 포인트 클라우드 (월드 좌표계, valid 픽셀 순서)
        mask_map: {object_id: (H, W) bool ndarray}
        image_shape: (H, W)
        valid_mask: depth_to_pointcloud(return_valid_mask=True)의 (H, W) bool.
                    None이면 모든 픽셀이 valid하다고 가정한다 (이때 포인트 수는
                    H*W와 같아야 한다).

    Returns:
        {object_id: PointCloud}
    """
    h, w = image_shape
    points = np.asarray(pcd_world.points)
    total = h * w

    if valid_mask is None:
        if len(points) != total:
            raise ValueError(
                f"valid_mask 없이 포인트 수({len(points)}) != H*W({total}). "
                "depth_to_pointcloud(return_valid_mask=True)의 valid를 전달하세요."
            )
        valid_flat = np.ones(total, dtype=bool)
    else:
        valid_flat = valid_mask.flatten()
        if int(valid_flat.sum()) != len(points):
            raise ValueError(
                f"valid 픽셀 수({int(valid_flat.sum())})와 포인트 수({len(points)}) 불일치"
            )

    # 픽셀(flat index) → 포인트 index 역매핑 (invalid 픽셀 = -1)
    pixel_to_point = np.full(total, -1, dtype=np.int64)
    pixel_to_point[np.where(valid_flat)[0]] = np.arange(len(points))

    result: dict[str, o3d.geometry.PointCloud] = {}
    for obj_id, mask in mask_map.items():
        flat_mask = mask.flatten()
        if len(flat_mask) != total:
            continue
        pt_idx = pixel_to_point[flat_mask]
        pt_idx = pt_idx[pt_idx >= 0]
        if len(pt_idx) == 0:
            continue
        obj_pcd = o3d.geometry.PointCloud()
        obj_pcd.points = o3d.utility.Vector3dVector(points[pt_idx])
        result[obj_id] = obj_pcd
    return result


def pointcloud_to_bbox(
    pcd: o3d.geometry.PointCloud,
    use_oriented: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """포인트 클라우드 → (center, size) 형태의 AABB or OBB.

    Returns:
        center: [x, y, z]
        size: [sx, sy, sz]
    """
    if len(pcd.points) == 0:
        return np.zeros(3), np.zeros(3)

    if use_oriented:
        obb = pcd.get_oriented_bounding_box()
        center = np.asarray(obb.center)
        extent = np.asarray(obb.extent)
        return center, extent
    else:
        aabb = pcd.get_axis_aligned_bounding_box()
        center = np.asarray(aabb.get_center())
        extent = np.asarray(aabb.get_extent())
        return center, extent


# ---------------------------------------------------------------------------
# Occlusion 추정 (단순 카메라 광선 기반)
# ---------------------------------------------------------------------------

def estimate_occlusion_ratio(
    target_pcd: o3d.geometry.PointCloud,
    all_pcd: o3d.geometry.PointCloud,
    camera_pos: np.ndarray = np.array([0.0, 0.0, 1.5]),
    n_rays: int = 50,
) -> float:
    """target 객체의 occlusion 비율을 추정한다.

    target 포인트에서 카메라 방향으로 rays를 쐈을 때 다른 포인트와 교차하면 occluded.
    """
    target_pts = np.asarray(target_pcd.points)
    all_pts = np.asarray(all_pcd.points)

    if len(target_pts) == 0 or len(all_pts) == 0:
        return 0.0

    rng = np.random.default_rng(42)
    sample_idx = rng.choice(len(target_pts), size=min(n_rays, len(target_pts)), replace=False)
    sample_pts = target_pts[sample_idx]

    occluded = 0
    for pt in sample_pts:
        direction = camera_pos - pt
        d_len = np.linalg.norm(direction)
        if d_len < 1e-6:
            continue
        direction = direction / d_len
        # 다른 포인트가 pt ↔ camera 사이에 있는지 확인
        diffs = all_pts - pt
        proj = diffs @ direction  # 각 포인트의 ray 방향 투영
        transverse = diffs - proj[:, None] * direction[None, :]
        t_dist = np.linalg.norm(transverse, axis=1)
        # 1. ray 방향 앞 (0 < proj < d_len), 2. 충분히 가까운 (t_dist < 0.03m)
        mask = (proj > 0.01) & (proj < d_len - 0.01) & (t_dist < 0.03)
        if np.any(mask):
            occluded += 1

    return occluded / max(len(sample_pts), 1)


# ---------------------------------------------------------------------------
# 메인: RGB-D → SceneGraph
# ---------------------------------------------------------------------------

def rgbd_to_scene_graph(
    rgb_image: np.ndarray,
    depth_image: np.ndarray,
    intrinsics: CameraIntrinsics,
    extrinsic: np.ndarray,
    role_map: dict[str, Role],
    mask_map: Optional[dict[str, np.ndarray]] = None,
    body_map_gt: Optional[dict[str, list[float]]] = None,
    scene_id: str = "rgbd_scene",
    support_bounds: Optional[dict] = None,
) -> SceneGraph:
    """RGB-D 입력 → SceneGraph 변환 (Track A와 동일 스키마).

    두 가지 모드:
      A) mask_map 제공: 픽셀 마스크로 객체 분리 → bbox 계산
      B) body_map_gt 제공: Ground-truth PyBullet 위치 (Track B 개발/검증용)

    Args:
        rgb_image:   (H, W, 3) uint8
        depth_image: (H, W) float32, 미터 단위
        intrinsics:  카메라 내부 파라미터
        extrinsic:   (4, 4) 카메라 → 월드 변환 행렬
        role_map:    {object_id: Role}
        mask_map:    {object_id: (H, W) bool} — None이면 body_map_gt 사용
        body_map_gt: {object_id: [x, y, z, sx, sy, sz]} — GT 위치/크기
        scene_id:    결과 SceneGraph ID
        support_bounds: {"x": [lo, hi], "y": [lo, hi]} — 테이블 경계

    Returns:
        SceneGraph (Track A와 동일 스키마)
    """
    h, w = depth_image.shape

    # ── 포인트 클라우드 생성 (valid mask 포함 — Mode A 픽셀 매핑용) ──────
    pcd_cam, valid_mask = depth_to_pointcloud(
        depth_image, intrinsics, return_valid_mask=True
    )
    pcd_world = transform_pointcloud(pcd_cam, extrinsic)

    # ── Support plane 추정 ───────────────────────────────────────────────
    if len(pcd_world.points) > 100:
        _, plane_z = estimate_support_plane(pcd_world)
    else:
        plane_z = 0.0

    # ── 테이블 bounds ────────────────────────────────────────────────────
    if support_bounds is None:
        pts_arr = np.asarray(pcd_world.points)
        if len(pts_arr) > 0:
            support_bounds = {
                "x": [float(pts_arr[:, 0].min()), float(pts_arr[:, 0].max())],
                "y": [float(pts_arr[:, 1].min()), float(pts_arr[:, 1].max())],
            }
        else:
            support_bounds = {"x": [0.0, 1.0], "y": [-0.5, 0.5]}

    support_surfaces = [
        SupportSurface(
            id="table_detected",
            type="plane",
            height=plane_z,
            bounds=support_bounds,
        )
    ]

    # ── 객체 위치/크기 추출 ──────────────────────────────────────────────
    objects: list[ObjectNode] = []
    perception_margins: dict[str, float] = {}

    if body_map_gt is not None:
        # Mode B: Ground-truth 위치 사용 (검증용)
        for obj_id, pose in body_map_gt.items():
            pos = list(pose[:3])
            size = list(pose[3:6]) if len(pose) >= 6 else [0.06, 0.06, 0.08]
            role = role_map.get(obj_id, Role.OBSTACLE)
            movable = (role != Role.DESTINATION)
            obj_shape = "tray" if role == Role.DESTINATION else "block"
            objects.append(ObjectNode(
                id=obj_id,
                role=role,
                position=pos,
                size=size,
                movable=movable,
                shape=obj_shape,
            ))
            perception_margins[obj_id] = 1.0  # GT는 완전 인식

    elif mask_map is not None:
        # Mode A: 픽셀 마스크로 분리 (픽셀↔포인트 역매핑)
        obj_pcds = extract_object_pointclouds(
            pcd_world, mask_map, (h, w), valid_mask=valid_mask
        )
        for obj_id, obj_pcd in obj_pcds.items():
            if len(obj_pcd.points) < 10:
                continue
            center, size = pointcloud_to_bbox(obj_pcd)
            # Z 오프셋 보정: 객체 바닥 = plane_z
            center[2] = plane_z + size[2] / 2.0

            role = role_map.get(obj_id, Role.OBSTACLE)
            movable = (role != Role.DESTINATION)
            obj_shape = "tray" if role == Role.DESTINATION else "block"
            objects.append(ObjectNode(
                id=obj_id,
                role=role,
                position=center.tolist(),
                size=np.maximum(size, 0.02).tolist(),
                movable=movable,
                shape=obj_shape,
            ))

            # occlusion 추정
            if role == Role.TARGET:
                occ = estimate_occlusion_ratio(obj_pcd, pcd_world)
                perception_margins[obj_id] = max(0.0, 1.0 - occ)
            else:
                perception_margins[obj_id] = 1.0

    # 관계 추론 (인접 객체 NEAR 관계)
    relations: list[Relation] = []
    for i, obj_a in enumerate(objects):
        for j, obj_b in enumerate(objects):
            if i >= j:
                continue
            dist = np.linalg.norm(
                np.array(obj_a.position) - np.array(obj_b.position)
            )
            if dist < 0.20:  # 20cm 이내 → NEAR
                relations.append(Relation(
                    type="NEAR",
                    source=obj_a.id,
                    target=obj_b.id,
                    distance_m=round(float(dist), 4),
                ))

    # meta에 perception_margins 포함
    meta = {
        "source": "rgbd",
        "scene_id": scene_id,
        "plane_z": float(plane_z),
        "perception_margins": perception_margins,
    }

    return SceneGraph(
        scene_id=scene_id,
        support_surfaces=support_surfaces,
        objects=objects,
        relations=relations,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# PyBullet에서 RGB-D 캡처 (DIRECT mode 지원)
# ---------------------------------------------------------------------------

def capture_rgbd_from_pybullet(
    camera_pos: list[float] = [0.5, 0.0, 1.2],
    target_pos: list[float] = [0.5, 0.0, 0.0],
    up_vec: list[float] = [0, 0, 1],
    fov: float = 60.0,
    width: int = 640,
    height: int = 480,
    near: float = 0.01,
    far: float = 3.5,
) -> tuple[np.ndarray, np.ndarray, CameraIntrinsics, np.ndarray]:
    """PyBullet에서 RGB + Depth 이미지를 캡처한다.

    Returns:
        rgb: (H, W, 3) uint8
        depth_linear: (H, W) float32, 미터 단위 선형 depth
        intrinsics: 카메라 내부 파라미터
        extrinsic: (4, 4) 카메라 → 월드 변환 행렬
    """
    import pybullet as p

    from scene_builder import get_client

    client = get_client()

    view_mat = p.computeViewMatrix(
        cameraEyePosition=camera_pos,
        cameraTargetPosition=target_pos,
        cameraUpVector=up_vec,
        physicsClientId=client,
    )
    proj_mat = p.computeProjectionMatrixFOV(
        fov=fov, aspect=width / height,
        nearVal=near, farVal=far,
        physicsClientId=client,
    )

    _, _, rgb_flat, depth_flat, _ = p.getCameraImage(
        width=width, height=height,
        viewMatrix=view_mat,
        projectionMatrix=proj_mat,
        physicsClientId=client,
    )

    rgb = np.array(rgb_flat, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]

    # PyBullet 비선형 depth → 선형 depth (미터)
    depth_buf = np.array(depth_flat, dtype=np.float32).reshape(height, width)
    depth_linear = far * near / (far - (far - near) * depth_buf)

    intrinsics = CameraIntrinsics.from_pybullet_fov(width, height, fov)

    # View matrix → extrinsic (카메라 → 월드)
    view_np = np.array(view_mat).reshape(4, 4).T  # column-major → row-major
    extrinsic = np.linalg.inv(view_np)

    return rgb, depth_linear, intrinsics, extrinsic
