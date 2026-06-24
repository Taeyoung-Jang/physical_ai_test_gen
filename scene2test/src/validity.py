"""validity.py — numpy 기반 해석적 유효성 필터.

PyBullet을 전혀 사용하지 않는다.
1,000개 mutation 후보를 < 1초에 필터링하는 것이 목표.

핵심 함수:
  aabb_overlap        : 두 AABB 겹침 여부
  point_in_bounds     : 점이 bounds 안에 있는지
  is_valid_base_scene : 생성된 base scene 유효성
  is_valid_mutation   : mutation 적용 후 scene 유효성
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from scene_graph import ObjectNode, Role, SceneGraph


# ---------------------------------------------------------------------------
# 기하 유틸
# ---------------------------------------------------------------------------

def aabb_overlap(
    center_a: np.ndarray,
    size_a: np.ndarray,
    center_b: np.ndarray,
    size_b: np.ndarray,
    margin: float = 0.0,
) -> bool:
    """두 axis-aligned bounding box 가 겹치는지 반환한다 (2D XY 기준).

    margin > 0이면 gap이 margin 미만일 때도 True.
    """
    half_a = size_a[:2] / 2 + margin
    half_b = size_b[:2] / 2 + margin
    delta = np.abs(center_a[:2] - center_b[:2])
    return bool(np.all(delta < half_a + half_b))


def point_in_bounds(
    point: np.ndarray,
    bounds: dict[str, list[float]],
    margin: float = 0.0,
) -> bool:
    """점이 bounds {"x": [min,max], "y": [min,max]} 안에 있는지 반환한다."""
    x_ok = bounds["x"][0] + margin <= point[0] <= bounds["x"][1] - margin
    y_ok = bounds["y"][0] + margin <= point[1] <= bounds["y"][1] - margin
    return x_ok and y_ok


def objects_overlap(objects: list[ObjectNode], margin: float = 0.005) -> bool:
    """객체 리스트에서 겹치는 쌍이 하나라도 있으면 True."""
    n = len(objects)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = objects[i], objects[j]
            if a.role == Role.HUMAN_ZONE or b.role == Role.HUMAN_ZONE:
                continue  # human_zone은 충돌 shape 없음
            ca = np.array(a.position)
            cb = np.array(b.position)
            sa = np.array(a.size)
            sb = np.array(b.size)
            if aabb_overlap(ca, sa, cb, sb, margin=margin):
                return True
    return False


def distance_xy(a: ObjectNode, b: ObjectNode) -> float:
    return float(np.linalg.norm(
        np.array(a.position[:2]) - np.array(b.position[:2])
    ))


def robot_to_target_distance(
    target: ObjectNode,
    robot_base: list[float],
) -> float:
    return float(np.linalg.norm(
        np.array(target.position) - np.array(robot_base)
    ))


# ---------------------------------------------------------------------------
# Base scene 유효성
# ---------------------------------------------------------------------------

def is_valid_base_scene(
    sg: SceneGraph,
    robot_cfg: dict,
    verbose: bool = False,
) -> bool:
    """생성된 base scene 이 다음 조건을 모두 만족하는지 확인한다.

    1. target이 존재하고 reach annulus 내에 있음
    2. destination이 존재
    3. 모든 객체가 table bounds 안에 있음
    4. 객체 간 비현실적 overlap 없음
    5. target ↔ destination 최소 거리 유지 (구분 가능성)
    6. destination이 reach 안에 있음
    """
    def fail(reason: str) -> bool:
        if verbose:
            print(f"  [invalid] {reason}")
        return False

    robot_base = robot_cfg["robot"]["base_position"]
    max_reach = robot_cfg["robot"]["max_reach"]
    min_reach = robot_cfg["robot"]["min_reach"]

    target = sg.target()
    destination = sg.destination()

    if target is None:
        return fail("target 없음")
    if destination is None:
        return fail("destination 없음")
    if not sg.support_surfaces:
        return fail("support_surface 없음")

    bounds = sg.support_surfaces[0].bounds

    # 1. target reach 검사
    dist_t = robot_to_target_distance(target, robot_base)
    if dist_t > max_reach:
        return fail(f"target이 max_reach({max_reach}m) 밖: {dist_t:.3f}m")
    if dist_t < min_reach:
        return fail(f"target이 min_reach({min_reach}m) 안: {dist_t:.3f}m")

    # 2. destination reach 검사
    dist_d = robot_to_target_distance(destination, robot_base)
    if dist_d > max_reach:
        return fail(f"destination이 max_reach 밖: {dist_d:.3f}m")

    # 3. 모든 객체 table bounds 안
    for obj in sg.objects:
        if obj.role == Role.HUMAN_ZONE:
            continue
        half = np.array(obj.size[:2]) / 2
        center = np.array(obj.position[:2])
        obj_min = center - half
        obj_max = center + half
        if (obj_min[0] < bounds["x"][0] or obj_max[0] > bounds["x"][1] or
                obj_min[1] < bounds["y"][0] or obj_max[1] > bounds["y"][1]):
            return fail(f"{obj.id}가 table bounds 밖")

    # 4. 객체 간 overlap 없음
    if objects_overlap(sg.objects):
        return fail("객체 간 overlap 발생")

    # 5. target ↔ destination 최소 거리 (서로 식별 가능)
    min_sep = max(
        np.linalg.norm(np.array(target.size[:2])),
        np.linalg.norm(np.array(destination.size[:2])),
    ) * 0.6
    if distance_xy(target, destination) < min_sep:
        return fail(f"target ↔ destination 너무 가까움")

    # 6. human_zone이 robot_base → target 경로와 안전거리 이상 떨어져 있어야 함
    #    (nominal scene은 safety oracle도 통과해야 함)
    safety_distance = 0.30  # thresholds.yaml 기본값과 동기화
    robot_base_np = np.array(robot_base)
    t_np = np.array(target.position)
    for obj in sg.by_role(Role.HUMAN_ZONE):
        hz_pos = np.array(obj.position[:2])
        hz_r = obj.extra.get("radius", max(obj.size[:2]) / 2)
        # 경로 선분과 human_zone 중심 최소 거리 (2D)
        ab = t_np[:2] - robot_base_np[:2]
        ap = hz_pos - robot_base_np[:2]
        len_sq = float(np.dot(ab, ab))
        t_val = float(np.dot(ap, ab)) / len_sq if len_sq > 1e-12 else 0.0
        t_val = max(0.0, min(1.0, t_val))
        proj = robot_base_np[:2] + t_val * ab
        dist_to_path = float(np.linalg.norm(hz_pos - proj)) - hz_r
        if dist_to_path < safety_distance:
            return fail(
                f"{obj.id}가 robot 경로와 너무 가까움 ({dist_to_path:.3f}m < {safety_distance}m)"
            )

    return True


# ---------------------------------------------------------------------------
# Mutation 유효성
# ---------------------------------------------------------------------------

def is_valid_mutation(
    base_sg: SceneGraph,
    mutation_params: dict[str, float],
    robot_cfg: dict,
) -> bool:
    """mutation_params를 적용한 scene 이 최소한의 물리 유효성을 갖는지 검사한다.

    실제 scene 변형 없이 파라미터만 보고 numpy로 판단한다.
    scene_builder.apply_mutation 의 변형 로직과 일치시켜야 함.
    """
    import math as _math

    robot_base = robot_cfg["robot"]["base_position"]
    max_reach = robot_cfg["robot"]["max_reach"]
    min_reach = robot_cfg["robot"]["min_reach"]

    if not base_sg.support_surfaces:
        return False
    bounds = base_sg.support_surfaces[0].bounds

    target = base_sg.target()
    destination = base_sg.destination()
    obstacles = base_sg.obstacles()

    if target is None or destination is None:
        return False

    # --- mutation 후 target 위치 ---
    tx = target.position[0] + mutation_params.get("target_dx", 0.0)
    ty = target.position[1] + mutation_params.get("target_dy", 0.0)
    tz = target.position[2]
    t_pos = np.array([tx, ty, tz])
    t_size = np.array(target.size)

    # target이 bounds 안에 있어야 함
    half_t = t_size[:2] / 2
    if (tx - half_t[0] < bounds["x"][0] or tx + half_t[0] > bounds["x"][1] or
            ty - half_t[1] < bounds["y"][0] or ty + half_t[1] > bounds["y"][1]):
        return False

    # target이 reach 범위 안에 있어야 함
    dist_t = float(np.linalg.norm(t_pos - np.array(robot_base)))
    if dist_t > max_reach or dist_t < min_reach:
        return False

    # --- mutation 후 obstacle 위치 ---
    if obstacles:
        angle_deg = mutation_params.get("obstacle_angle", 0.0)
        dist_obs = mutation_params.get("obstacle_dist_to_target", 0.10)
        angle_rad = _math.radians(angle_deg)
        ox = tx + dist_obs * _math.cos(angle_rad)
        oy = ty + dist_obs * _math.sin(angle_rad)
        oz = obstacles[0].position[2]
        o_size = np.array(obstacles[0].size)
        o_pos = np.array([ox, oy, oz])

        # obstacle이 bounds 안에 있어야 함
        half_o = o_size[:2] / 2
        if (ox - half_o[0] < bounds["x"][0] or ox + half_o[0] > bounds["x"][1] or
                oy - half_o[1] < bounds["y"][0] or oy + half_o[1] > bounds["y"][1]):
            return False

        # target ↔ obstacle : 완전히 겹치면 안 됨 (약간 겹침은 허용 — clearance 실패 시나리오)
        delta_xy = np.abs(o_pos[:2] - t_pos[:2])
        combined_half = (t_size[:2] + o_size[:2]) / 2
        if np.all(delta_xy < combined_half * 0.3):
            return False  # 중심 80% 이상 겹침: 비현실적

    # --- tray 점유 시 두 번째 obstacle 위치 ---
    if len(obstacles) > 1 and round(mutation_params.get("tray_occupied", 0)) == 1:
        dest_pos = np.array(destination.position)
        blocker = obstacles[1]
        b_pos = np.array([dest_pos[0], dest_pos[1],
                           dest_pos[2] + destination.size[2]/2 + blocker.size[2]/2])
        b_size = np.array(blocker.size)
        # blocker가 bounds 안에 있어야 함
        half_b = b_size[:2] / 2
        if (b_pos[0] - half_b[0] < bounds["x"][0] or
                b_pos[0] + half_b[0] > bounds["x"][1] or
                b_pos[1] - half_b[1] < bounds["y"][0] or
                b_pos[1] + half_b[1] > bounds["y"][1]):
            return False

    # --- human_zone 위치 ---
    hz_x = mutation_params.get("human_zone_x")
    hz_y = mutation_params.get("human_zone_y")
    if hz_x is not None and hz_y is not None:
        if not (bounds["x"][0] <= hz_x <= bounds["x"][1] and
                bounds["y"][0] <= hz_y <= bounds["y"][1]):
            return False

    return True


# ---------------------------------------------------------------------------
# 배치 필터 (mutation 후보 1,000개를 벡터 연산으로 필터)
# ---------------------------------------------------------------------------

def filter_mutation_batch(
    base_sg: SceneGraph,
    candidates: list[dict],
    robot_cfg: dict,
) -> list[dict]:
    """후보 리스트에서 유효한 것만 반환한다 (numpy, PyBullet 미사용)."""
    return [c for c in candidates if is_valid_mutation(base_sg, c, robot_cfg)]
