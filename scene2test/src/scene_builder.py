"""scene_builder.py — PyBullet 장면 로드/초기화.

SceneGraph를 받아 PyBullet 월드에 객체들을 생성하고,
body_id_map {obj_id -> pybullet_body_id} 를 반환한다.
mutation_params를 받아 base SceneGraph를 변형한 장면도 구성한다.

실행 모드는 .env 의 PYBULLET_MODE 환경변수로 결정한다:
  DIRECT (기본) : 헤드리스, 배치 실행에 사용
  GUI           : 시각적 확인용
"""
from __future__ import annotations

import math
import os
from typing import Optional

import numpy as np
import pybullet as p
import pybullet_data

from scene_graph import ObjectNode, Role, SceneGraph


# ---------------------------------------------------------------------------
# 연결 관리
# ---------------------------------------------------------------------------

_client_id: Optional[int] = None


def connect(mode: Optional[str] = None) -> int:
    """PyBullet에 연결하고 client_id를 반환한다."""
    global _client_id
    if _client_id is not None:
        return _client_id

    mode_str = mode or os.environ.get("PYBULLET_MODE", "DIRECT")
    conn_mode = p.GUI if mode_str.upper() == "GUI" else p.DIRECT
    _client_id = p.connect(conn_mode)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=_client_id)
    p.setGravity(0, 0, -9.81, physicsClientId=_client_id)
    return _client_id


def disconnect() -> None:
    global _client_id
    if _client_id is not None:
        try:
            p.disconnect(physicsClientId=_client_id)
        except Exception:
            pass
        _client_id = None


def get_client() -> int:
    if _client_id is None:
        connect()
    return _client_id


def reset_simulation() -> None:
    cid = get_client()
    p.resetSimulation(physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)


# ---------------------------------------------------------------------------
# 색상 팔레트
# ---------------------------------------------------------------------------

_ROLE_COLORS: dict[str, list[float]] = {
    Role.TARGET:      [0.85, 0.15, 0.15, 1.0],   # 빨강
    Role.OBSTACLE:    [0.15, 0.35, 0.85, 1.0],   # 파랑
    Role.DESTINATION: [0.15, 0.75, 0.25, 1.0],   # 초록
    Role.HUMAN_ZONE:  [0.95, 0.65, 0.10, 0.45],  # 주황 반투명
    Role.DISTRACTOR:  [0.60, 0.60, 0.60, 1.0],   # 회색
}


def _role_color(role: str) -> list[float]:
    return _ROLE_COLORS.get(role, [0.7, 0.7, 0.7, 1.0])


# ---------------------------------------------------------------------------
# 기본 도형 생성
# ---------------------------------------------------------------------------

def create_box(
    position: list[float],
    half_extents: list[float],
    color: list[float],
    mass: float = 0.1,
    lateral_friction: float = 0.8,
) -> int:
    """AABB box를 생성하고 body_id를 반환한다."""
    cid = get_client()
    col_id = p.createCollisionShape(
        p.GEOM_BOX, halfExtents=half_extents, physicsClientId=cid
    )
    vis_id = p.createVisualShape(
        p.GEOM_BOX, halfExtents=half_extents, rgbaColor=color, physicsClientId=cid
    )
    body_id = p.createMultiBody(
        baseMass=mass,
        baseCollisionShapeIndex=col_id,
        baseVisualShapeIndex=vis_id,
        basePosition=position,
        physicsClientId=cid,
    )
    p.changeDynamics(body_id, -1, lateralFriction=lateral_friction, physicsClientId=cid)
    return body_id


def create_cylinder(
    position: list[float],
    radius: float,
    height: float,
    color: list[float],
    mass: float = 0.1,
) -> int:
    cid = get_client()
    col_id = p.createCollisionShape(
        p.GEOM_CYLINDER, radius=radius, height=height, physicsClientId=cid
    )
    vis_id = p.createVisualShape(
        p.GEOM_CYLINDER, radius=radius, length=height, rgbaColor=color, physicsClientId=cid
    )
    return p.createMultiBody(
        baseMass=mass,
        baseCollisionShapeIndex=col_id,
        baseVisualShapeIndex=vis_id,
        basePosition=position,
        physicsClientId=cid,
    )


def create_plane(height: float = 0.0) -> int:
    """테이블 지지면 평면을 생성한다."""
    cid = get_client()
    return p.loadURDF("plane.urdf", [0, 0, height - 0.01], physicsClientId=cid)


def create_table(bounds: dict, height: float = 0.0, thickness: float = 0.02) -> int:
    """bounds {"x": [min,max], "y": [min,max]} 로 테이블 상판을 생성한다."""
    x_min, x_max = bounds["x"]
    y_min, y_max = bounds["y"]
    cx = (x_min + x_max) / 2
    cy = (y_min + y_max) / 2
    hx = (x_max - x_min) / 2
    hy = (y_max - y_min) / 2
    hz = thickness / 2
    return create_box(
        position=[cx, cy, height - hz],
        half_extents=[hx, hy, hz],
        color=[0.55, 0.40, 0.25, 1.0],
        mass=0,  # 고정
    )


def create_human_zone(position: list[float], radius: float) -> int:
    """human_zone: 충돌 없이 시각적으로만 표시되는 실린더."""
    cid = get_client()
    height = 1.8
    vis_id = p.createVisualShape(
        p.GEOM_CYLINDER,
        radius=radius,
        length=height,
        rgbaColor=_role_color(Role.HUMAN_ZONE),
        physicsClientId=cid,
    )
    # 충돌 shape 없이 시각 전용 body
    return p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=-1,
        baseVisualShapeIndex=vis_id,
        basePosition=[position[0], position[1], height / 2],
        physicsClientId=cid,
    )


# ---------------------------------------------------------------------------
# ObjectNode → PyBullet body
# ---------------------------------------------------------------------------

def _spawn_object(obj: ObjectNode) -> int:
    """ObjectNode 하나를 PyBullet에 생성하고 body_id를 반환한다."""
    pos = list(obj.position)
    size = list(obj.size)
    color = _role_color(obj.role)
    mass = 0.0 if not obj.movable else 0.1

    if obj.role == Role.HUMAN_ZONE:
        radius = obj.extra.get("radius", max(size[0], size[1]) / 2)
        return create_human_zone(pos, radius)

    if obj.shape == "cylinder":
        radius = max(size[0], size[1]) / 2
        height = size[2]
        return create_cylinder(pos, radius, height, color, mass)

    # block / tray / bin / zone / default → box
    half_extents = [size[0] / 2, size[1] / 2, size[2] / 2]
    return create_box(pos, half_extents, color, mass)


# ---------------------------------------------------------------------------
# SceneGraph 로드
# ---------------------------------------------------------------------------

def load_scene(sg: SceneGraph) -> dict[str, int]:
    """SceneGraph를 PyBullet에 로드하고 {obj_id: body_id} 를 반환한다.

    호출 전 reset_simulation()이 완료되어 있어야 한다.
    """
    body_map: dict[str, int] = {}

    # 지지면
    for surf in sg.support_surfaces:
        table_id = create_table(surf.bounds, surf.height)
        body_map[surf.id] = table_id

    # 전체 평면 (중력/충돌 기반)
    create_plane(sg.support_surfaces[0].height if sg.support_surfaces else 0.0)

    # 객체
    for obj in sg.objects:
        body_id = _spawn_object(obj)
        body_map[obj.id] = body_id

    return body_map


# ---------------------------------------------------------------------------
# Mutation 적용
# ---------------------------------------------------------------------------

def apply_mutation(
    sg: SceneGraph,
    mutation_params: dict[str, float],
) -> SceneGraph:
    """base SceneGraph에 mutation_params를 적용해 새 SceneGraph를 반환한다.

    원본 sg는 수정하지 않는다(deep-copy 방식).
    """
    import copy
    mutated = copy.deepcopy(sg)

    target = mutated.target()
    obstacles = mutated.obstacles()
    destination = mutated.destination()
    human_zones = mutated.human_zones()

    # target 위치 이동
    dx = mutation_params.get("target_dx", 0.0)
    dy = mutation_params.get("target_dy", 0.0)
    if target is not None:
        target.position[0] += dx
        target.position[1] += dy

    # obstacle을 target 주변 지정 거리/각도로 이동
    if obstacles and target is not None:
        angle_deg = mutation_params.get("obstacle_angle", 0.0)
        dist = mutation_params.get("obstacle_dist_to_target", 0.10)
        angle_rad = math.radians(angle_deg)
        obs = obstacles[0]
        obs.position[0] = target.position[0] + dist * math.cos(angle_rad)
        obs.position[1] = target.position[1] + dist * math.sin(angle_rad)

    # tray 점유 (두 번째 obstacle을 tray 위로 이동)
    if destination is not None and len(obstacles) > 1:
        if round(mutation_params.get("tray_occupied", 0)) == 1:
            blocker = obstacles[1]
            blocker.position[0] = destination.position[0]
            blocker.position[1] = destination.position[1]
            blocker.position[2] = destination.position[2] + destination.size[2] / 2 + blocker.size[2] / 2

    # human_zone 위치
    hz_x = mutation_params.get("human_zone_x")
    hz_y = mutation_params.get("human_zone_y")
    if hz_x is not None and hz_y is not None:
        if human_zones:
            human_zones[0].position[0] = hz_x
            human_zones[0].position[1] = hz_y
        else:
            # human_zone이 없던 scene에 삽입
            mutated.objects.append(ObjectNode(
                id="human_zone_mutated",
                role=Role.HUMAN_ZONE,
                position=[hz_x, hz_y, 0.0],
                size=[0.30, 0.30, 1.80],
                movable=False,
                shape="cylinder",
                extra={"radius": 0.15},
            ))

    # occlusion_ratio → UnknownRegion 추가/갱신 (perception oracle용)
    occ_ratio = mutation_params.get("occlusion_ratio", 0.0)
    if occ_ratio > 0.0 and target is not None:
        from scene_graph import UnknownRegion
        mutated.unknown_regions = [
            UnknownRegion(
                id="occ_region_mutated",
                center=list(target.position),
                radius=0.10,
                occlusion_ratio=occ_ratio,
            )
        ]

    return mutated


def reset_and_load(sg: SceneGraph, mutation_params: Optional[dict] = None) -> dict[str, int]:
    """시뮬레이션을 리셋하고, mutation을 적용(옵션)한 SceneGraph를 로드한다."""
    reset_simulation()
    scene = apply_mutation(sg, mutation_params) if mutation_params else sg
    return load_scene(scene), scene


# ---------------------------------------------------------------------------
# 카메라 스냅샷
# ---------------------------------------------------------------------------

def capture_frame(
    width: int = 640,
    height: int = 480,
    cam_target: list[float] = (0.45, 0.0, 0.0),
    distance: float = 1.2,
    yaw: float = 45.0,
    pitch: float = -35.0,
) -> np.ndarray:
    """TinyRenderer로 RGB 프레임을 캡처해 (H, W, 3) uint8 배열을 반환한다."""
    cid = get_client()
    view_matrix = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=cam_target,
        distance=distance,
        yaw=yaw,
        pitch=pitch,
        roll=0,
        upAxisIndex=2,
        physicsClientId=cid,
    )
    proj_matrix = p.computeProjectionMatrixFOV(
        fov=60, aspect=width / height, nearVal=0.01, farVal=10.0, physicsClientId=cid
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height,
        viewMatrix=view_matrix,
        projectionMatrix=proj_matrix,
        renderer=p.ER_TINY_RENDERER,
        physicsClientId=cid,
    )
    # PyBullet DIRECT 모드에서는 flat list로 반환될 수 있음
    arr = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)
    return arr[:, :, :3]
