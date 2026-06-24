"""feature_extractor.py — Scene Graph + mutation params → 피처 벡터.

surrogate model의 입력 벡터를 생성한다:
  x = concat(scene_features[8], mutation_params[8])  → shape (16,)

scene_features는 SceneGraph 기하 정보만으로 계산 (PyBullet 불필요).
mutation_params는 Mutation Space Builder가 제공하는 dict.

피처 8종:
  0  target_robot_distance      : 로봇 ↔ target 유클리드 거리 (m)
  1  target_to_nearest_obstacle : target ↔ 가장 가까운 obstacle 거리 (m)
  2  path_min_clearance         : robot→target 직선 경로 주변 최소 obstacle 거리 (m)
  3  reach_margin               : max_reach - target_robot_distance (m)
  4  obstacle_on_path           : 경로와 obstacle AABB 교차 여부 (0/1)
  5  destination_occupied       : tray region 내 obstacle 존재 여부 (0/1)
  6  human_zone_min_distance    : 경로 ↔ human_zone 최소 거리 (m, 없으면 1.0)
  7  unknown_region_overlap     : occlusion region과 경로 겹침 비율 (0~1)

mutation_params 8종 (정규화 전 raw 값):
  target_dx, target_dy, obstacle_angle, obstacle_dist_to_target,
  human_zone_x, human_zone_y, tray_occupied, occlusion_ratio
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from scene_graph import ObjectNode, Role, SceneGraph

# 피처 이름 (순서 고정)
SCENE_FEATURE_NAMES = [
    "target_robot_distance",
    "target_to_nearest_obstacle",
    "path_min_clearance",
    "reach_margin",
    "obstacle_on_path",
    "destination_occupied",
    "human_zone_min_distance",
    "unknown_region_overlap",
]

MUTATION_PARAM_NAMES = [
    "target_dx",
    "target_dy",
    "obstacle_angle",
    "obstacle_dist_to_target",
    "human_zone_x",
    "human_zone_y",
    "tray_occupied",
    "occlusion_ratio",
]

FEATURE_NAMES = SCENE_FEATURE_NAMES + MUTATION_PARAM_NAMES


# ---------------------------------------------------------------------------
# 기하 유틸 (numpy 전용)
# ---------------------------------------------------------------------------

def _dist_xy(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a[:2] - b[:2]))


def _dist_3d(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _point_to_segment_dist_2d(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """점 p와 선분 a-b 사이의 2D 최소 거리."""
    ab = b[:2] - a[:2]
    ap = p[:2] - a[:2]
    len_sq = float(np.dot(ab, ab))
    if len_sq < 1e-12:
        return float(np.linalg.norm(ap))
    t = float(np.dot(ap, ab)) / len_sq
    t = max(0.0, min(1.0, t))
    proj = a[:2] + t * ab
    return float(np.linalg.norm(p[:2] - proj))


def _segment_aabb_overlap_2d(
    seg_a: np.ndarray,
    seg_b: np.ndarray,
    aabb_center: np.ndarray,
    aabb_half: np.ndarray,
) -> bool:
    """선분 [seg_a, seg_b]이 AABB(center, half_extents)와 겹치는지 2D 검사."""
    # 선분을 n_check개 점으로 샘플링해 AABB 내부 여부 확인 (빠른 근사)
    n_check = 10
    for t in np.linspace(0, 1, n_check):
        pt = seg_a[:2] + t * (seg_b[:2] - seg_a[:2])
        if np.all(np.abs(pt - aabb_center[:2]) < aabb_half[:2]):
            return True
    return False


# ---------------------------------------------------------------------------
# Scene Features 계산
# ---------------------------------------------------------------------------

def compute_scene_features(
    sg: SceneGraph,
    robot_base: list[float],
    max_reach: float,
) -> dict[str, float]:
    """SceneGraph에서 8종 피처를 계산한다."""
    feats: dict[str, float] = {k: 0.0 for k in SCENE_FEATURE_NAMES}

    target = sg.target()
    destination = sg.destination()
    obstacles = sg.obstacles()
    human_zones = sg.human_zones()

    robot_pos = np.array(robot_base)

    if target is None:
        return feats

    t_pos = np.array(target.position)

    # 0. target_robot_distance
    dist_t = _dist_3d(t_pos, robot_pos)
    feats["target_robot_distance"] = dist_t

    # 3. reach_margin
    feats["reach_margin"] = max_reach - dist_t

    # 경로 직선 (robot XY → target XY)
    path_start = robot_pos
    path_end = t_pos

    # 1. target_to_nearest_obstacle
    if obstacles:
        dists_to_target = [
            _dist_xy(np.array(o.position), t_pos) for o in obstacles
        ]
        feats["target_to_nearest_obstacle"] = min(dists_to_target)
    else:
        feats["target_to_nearest_obstacle"] = 1.0

    # 2. path_min_clearance  &  4. obstacle_on_path
    if obstacles:
        min_path_dist = float("inf")
        on_path = False
        for obs in obstacles:
            obs_pos = np.array(obs.position)
            obs_half = np.array(obs.size) / 2

            # 경로 ↔ obstacle 중심 최소 거리 (2D)
            d = _point_to_segment_dist_2d(obs_pos, path_start, path_end)
            # 표면까지의 거리 = 중심 거리 - obstacle 수평 반경
            surface_d = d - max(obs_half[:2])
            min_path_dist = min(min_path_dist, surface_d)

            # 경로와 obstacle AABB 교차 여부
            if _segment_aabb_overlap_2d(path_start, path_end, obs_pos, obs_half):
                on_path = True

        feats["path_min_clearance"] = min_path_dist
        feats["obstacle_on_path"] = 1.0 if on_path else 0.0
    else:
        feats["path_min_clearance"] = 1.0
        feats["obstacle_on_path"] = 0.0

    # 5. destination_occupied
    if destination and obstacles:
        dest_pos = np.array(destination.position)
        dest_half = np.array(destination.size) / 2
        occupied = any(
            np.all(np.abs(np.array(o.position[:2]) - dest_pos[:2]) <
                   (dest_half[:2] + np.array(o.size[:2]) / 2))
            for o in obstacles
        )
        feats["destination_occupied"] = 1.0 if occupied else 0.0
    else:
        feats["destination_occupied"] = 0.0

    # 6. human_zone_min_distance (경로 샘플 포인트 ↔ human_zone)
    if human_zones:
        n_path_pts = 12
        path_pts = [
            path_start + t * (path_end - path_start)
            for t in np.linspace(0, 1, n_path_pts)
        ]
        min_hz_dist = float("inf")
        for hz in human_zones:
            hz_pos = np.array(hz.position)
            hz_r = hz.extra.get("radius", max(hz.size[:2]) / 2)
            for pt in path_pts:
                d = _dist_xy(pt, hz_pos) - hz_r
                min_hz_dist = min(min_hz_dist, d)
        feats["human_zone_min_distance"] = max(0.0, min_hz_dist)
    else:
        feats["human_zone_min_distance"] = 1.0

    # 7. unknown_region_overlap (occlusion region과 경로 겹침 비율)
    if sg.unknown_regions:
        n_path_pts = 20
        path_pts = [
            path_start + t * (path_end - path_start)
            for t in np.linspace(0, 1, n_path_pts)
        ]
        overlapping = 0
        for ur in sg.unknown_regions:
            ur_center = np.array(ur.center)
            for pt in path_pts:
                if _dist_xy(pt, ur_center) <= ur.radius:
                    overlapping += 1
        feats["unknown_region_overlap"] = overlapping / n_path_pts
    else:
        feats["unknown_region_overlap"] = 0.0

    return feats


# ---------------------------------------------------------------------------
# Mutation Params → 정규화된 벡터
# ---------------------------------------------------------------------------

# 정규화 범위 (MUTATION_PARAM_NAMES 순서와 일치)
_MUTATION_RANGES = [
    (-0.10, 0.10),   # target_dx
    (-0.10, 0.10),   # target_dy
    (0, 360),        # obstacle_angle
    (0.02, 0.20),    # obstacle_dist_to_target
    (0.20, 0.80),    # human_zone_x
    (-0.40, 0.40),   # human_zone_y
    (0, 1),          # tray_occupied
    (0.0, 0.6),      # occlusion_ratio
]


def normalize_mutation_params(params: dict[str, float]) -> np.ndarray:
    """mutation_params dict를 [0,1] 정규화된 numpy 벡터로 변환한다."""
    vec = np.zeros(len(MUTATION_PARAM_NAMES))
    for i, (name, (lo, hi)) in enumerate(zip(MUTATION_PARAM_NAMES, _MUTATION_RANGES)):
        raw = params.get(name, 0.0)
        vec[i] = (raw - lo) / (hi - lo) if hi > lo else 0.0
    return np.clip(vec, 0.0, 1.0)


def mutation_params_to_raw_vector(params: dict[str, float]) -> np.ndarray:
    """mutation_params dict를 raw (정규화 없는) numpy 벡터로 변환한다."""
    return np.array([params.get(name, 0.0) for name in MUTATION_PARAM_NAMES])


# ---------------------------------------------------------------------------
# 최종 피처 벡터 생성
# ---------------------------------------------------------------------------

def build_feature_vector(
    sg: SceneGraph,
    mutation_params: dict[str, float],
    robot_base: list[float],
    max_reach: float,
    normalize_mutations: bool = True,
) -> np.ndarray:
    """scene_features + mutation_params를 concat한 (16,) 벡터를 반환한다."""
    scene_feats = compute_scene_features(sg, robot_base, max_reach)
    scene_vec = np.array([scene_feats[k] for k in SCENE_FEATURE_NAMES])

    if normalize_mutations:
        mut_vec = normalize_mutation_params(mutation_params)
    else:
        mut_vec = mutation_params_to_raw_vector(mutation_params)

    return np.concatenate([scene_vec, mut_vec])


def build_feature_batch(
    sg: SceneGraph,
    mutation_list: list[dict[str, float]],
    robot_base: list[float],
    max_reach: float,
    normalize_mutations: bool = True,
) -> np.ndarray:
    """N개의 mutation에 대해 (N, 16) 행렬을 반환한다."""
    scene_feats = compute_scene_features(sg, robot_base, max_reach)
    scene_vec = np.array([scene_feats[k] for k in SCENE_FEATURE_NAMES])

    rows = []
    for params in mutation_list:
        if normalize_mutations:
            mut_vec = normalize_mutation_params(params)
        else:
            mut_vec = mutation_params_to_raw_vector(params)
        rows.append(np.concatenate([scene_vec, mut_vec]))

    return np.array(rows)


# ---------------------------------------------------------------------------
# 피처 설명 출력 (디버그용)
# ---------------------------------------------------------------------------

def describe_features(
    sg: SceneGraph,
    mutation_params: dict[str, float],
    robot_base: list[float],
    max_reach: float,
) -> None:
    feats = compute_scene_features(sg, robot_base, max_reach)
    mut_vec = normalize_mutation_params(mutation_params)
    print("Scene Features:")
    for k in SCENE_FEATURE_NAMES:
        print(f"  {k:35s} = {feats[k]:.4f}")
    print("Mutation Params (normalized):")
    for name, val in zip(MUTATION_PARAM_NAMES, mut_vec):
        raw = mutation_params.get(name, 0.0)
        print(f"  {name:35s} = {val:.4f}  (raw={raw})")
