"""mutation_space.py — Mutation Space Builder + 샘플러 3종.

하나의 mutation_params dict = 하나의 테스트 장면.

샘플러:
  sample_random(sg, n)           : 균일 랜덤 (일반 탐색)
  sample_latin_hypercube(sg, n)  : Latin Hypercube Sampling (초기 seed 다양성)
  sample_boundary_seeds(sg)      : 경계 조건 근처 시드 (reach 최대, clearance 최소 등)

모두 validity.filter_mutation_batch 를 통과한 유효 후보만 반환한다.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import qmc  # Latin Hypercube

from scene_graph import SceneGraph
from validity import filter_mutation_batch

# ---------------------------------------------------------------------------
# 파라미터 공간 정의 (8차원)
# ---------------------------------------------------------------------------

PARAM_NAMES: list[str] = [
    "target_dx",
    "target_dy",
    "obstacle_angle",
    "obstacle_dist_to_target",
    "human_zone_x",
    "human_zone_y",
    "tray_occupied",
    "occlusion_ratio",
]

# (lo, hi) 연속 범위; tray_occupied는 round()로 이진 처리
PARAM_BOUNDS: list[tuple[float, float]] = [
    (-0.10, 0.10),   # target_dx
    (-0.10, 0.10),   # target_dy
    (0.0, 360.0),    # obstacle_angle
    (0.02, 0.20),    # obstacle_dist_to_target
    (0.20, 0.80),    # human_zone_x
    (-0.40, 0.40),   # human_zone_y
    (0.0, 1.0),      # tray_occupied (이진)
    (0.0, 0.60),     # occlusion_ratio
]

_LO = np.array([b[0] for b in PARAM_BOUNDS])
_HI = np.array([b[1] for b in PARAM_BOUNDS])

# human_zone이 포함될 확률 (약 20%)
_HUMAN_ZONE_PROB = 0.20


# ---------------------------------------------------------------------------
# 내부: [0,1]^8 벡터 → params dict
# ---------------------------------------------------------------------------

def _unit_to_params(u: np.ndarray, human_zone_active: bool = True) -> dict[str, float]:
    """[0,1]^8 단위 벡터를 params dict로 변환.

    human_zone_active=False 이면 human_zone_x/y 키를 포함하지 않는다.
    apply_mutation은 이 키 부재를 "human_zone 없음"으로 해석한다.
    """
    raw = _LO + u * (_HI - _LO)
    params = {name: float(raw[i]) for i, name in enumerate(PARAM_NAMES)}
    params["tray_occupied"] = float(round(params["tray_occupied"]))
    if not human_zone_active:
        params.pop("human_zone_x", None)
        params.pop("human_zone_y", None)
    return params


def _params_to_unit(params: dict[str, float]) -> np.ndarray:
    raw = np.array([params.get(name, 0.0) for name in PARAM_NAMES])
    return np.clip((raw - _LO) / (_HI - _LO), 0.0, 1.0)


# ---------------------------------------------------------------------------
# 샘플러 3종
# ---------------------------------------------------------------------------

def sample_random(
    sg: SceneGraph,
    robot_cfg: dict,
    n: int = 1000,
    seed: Optional[int] = None,
    human_zone_prob: float = _HUMAN_ZONE_PROB,
) -> list[dict[str, float]]:
    """유효 mutation 공간에서 균일 랜덤 샘플링 후 validity 필터를 적용한다.

    human_zone_prob: 각 mutation에 human_zone을 포함할 확률 (기본 20%).
    """
    rng = np.random.default_rng(seed)
    oversample = max(n * 3, 3000)
    u = rng.uniform(0.0, 1.0, (oversample, len(PARAM_NAMES)))
    hz_active = rng.random(oversample) < human_zone_prob
    candidates = [_unit_to_params(u[i], hz_active[i]) for i in range(oversample)]
    valid = filter_mutation_batch(sg, candidates, robot_cfg)
    return valid[:n]


def sample_latin_hypercube(
    sg: SceneGraph,
    robot_cfg: dict,
    n: int = 100,
    seed: Optional[int] = None,
    human_zone_prob: float = _HUMAN_ZONE_PROB,
) -> list[dict[str, float]]:
    """Latin Hypercube Sampling — 파라미터 공간을 고르게 커버한다.

    초기 seed 선택이나 비교 실험의 random search 기준선에 사용한다.
    """
    sampler = qmc.LatinHypercube(d=len(PARAM_NAMES), seed=seed)
    oversample = max(n * 3, 300)
    u = sampler.random(oversample)
    rng = np.random.default_rng(seed)
    hz_active = rng.random(oversample) < human_zone_prob
    candidates = [_unit_to_params(u[i], hz_active[i]) for i in range(oversample)]
    valid = filter_mutation_batch(sg, candidates, robot_cfg)
    return valid[:n]


def sample_boundary_seeds(
    sg: SceneGraph,
    robot_cfg: dict,
) -> list[dict[str, float]]:
    """실패 경계 근처에 집중된 시드 후보를 반환한다.

    Active Failure Search 초기 라운드에서 surrogate 학습 데이터를
    실패 경계 근처에 배치하기 위해 사용한다.

    포함되는 경계 조건 유형:
      - reach 최대 (target을 최대 도달 가능 위치로)
      - clearance 최소 (obstacle을 target에 최대한 근접)
      - path blocked (obstacle을 경로 중앙에)
      - human zone path 진입
      - destination 점유
      - occlusion 최대
      - reach 최소 (target을 robot 바로 앞으로)
    """
    seeds = []
    robot_base = np.array(robot_cfg["robot"]["base_position"])
    max_reach = robot_cfg["robot"]["max_reach"]
    target = sg.target()
    if target is None:
        return seeds

    t_pos = np.array(target.position[:2])

    # target에서 robot_base 방향 단위 벡터
    direction = t_pos - robot_base[:2]
    d_norm = np.linalg.norm(direction)
    if d_norm > 1e-6:
        unit = direction / d_norm
    else:
        unit = np.array([1.0, 0.0])

    # -- 1. reach 최대: target을 robot에서 max_reach의 95% 거리 방향으로 --
    r_target = max_reach * 0.92
    far_pos = robot_base[:2] + unit * r_target
    seeds.append({
        "target_dx": float(far_pos[0] - t_pos[0]),
        "target_dy": float(far_pos[1] - t_pos[1]),
        "obstacle_angle": 90.0,
        "obstacle_dist_to_target": 0.12,
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.0,
    })

    # -- 2. clearance 최소: obstacle을 target에 gripper 폭+여유만큼 붙임 --
    gripper_w = robot_cfg["robot"]["gripper_open_width"]
    seeds.append({
        "target_dx": 0.0,
        "target_dy": 0.0,
        "obstacle_angle": 0.0,
        "obstacle_dist_to_target": gripper_w * 0.9,  # 폭보다 약간 작게
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.0,
    })

    # -- 3. path blocked: obstacle을 경로 중앙에 --
    path_mid = (robot_base[:2] + t_pos) / 2
    mid_angle = math.degrees(math.atan2(
        path_mid[1] - t_pos[1], path_mid[0] - t_pos[0]
    ))
    dist_mid = float(np.linalg.norm(path_mid - t_pos))
    seeds.append({
        "target_dx": 0.0,
        "target_dy": 0.0,
        "obstacle_angle": mid_angle % 360,
        "obstacle_dist_to_target": max(0.04, dist_mid),
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.0,
    })

    # -- 4. human zone path 진입: human_zone을 경로 중간에 (의도적 human_risk 시드) --
    if sg.support_surfaces:
        bounds = sg.support_surfaces[0].bounds
        hx = float(np.clip(path_mid[0], bounds["x"][0], bounds["x"][1]))
        hy = float(np.clip(path_mid[1], bounds["y"][0], bounds["y"][1]))
        seeds.append({
            "target_dx": 0.0,
            "target_dy": 0.0,
            "obstacle_angle": 90.0,
            "obstacle_dist_to_target": 0.12,
            "human_zone_x": hx,
            "human_zone_y": hy,
            "tray_occupied": 0.0,
            "occlusion_ratio": 0.0,
        })

    # -- 5. destination 점유 --
    seeds.append({
        "target_dx": 0.0,
        "target_dy": 0.0,
        "obstacle_angle": 90.0,
        "obstacle_dist_to_target": 0.12,
        "tray_occupied": 1.0,
        "occlusion_ratio": 0.0,
    })

    # -- 6. occlusion 최대 --
    seeds.append({
        "target_dx": 0.0,
        "target_dy": 0.0,
        "obstacle_angle": 90.0,
        "obstacle_dist_to_target": 0.12,
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.55,
    })

    # -- 7. reach 최소: target을 robot 바로 앞 min_reach+여유로 --
    min_reach = robot_cfg["robot"]["min_reach"]
    near_pos = robot_base[:2] + unit * (min_reach + 0.02)
    seeds.append({
        "target_dx": float(near_pos[0] - t_pos[0]),
        "target_dy": float(near_pos[1] - t_pos[1]),
        "obstacle_angle": 90.0,
        "obstacle_dist_to_target": 0.12,
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.0,
    })

    # validity 필터
    return filter_mutation_batch(sg, seeds, robot_cfg)


# ---------------------------------------------------------------------------
# 편의 함수: 초기 seed 세트 (LHS + boundary 혼합)
# ---------------------------------------------------------------------------

def sample_initial_seeds(
    sg: SceneGraph,
    robot_cfg: dict,
    k: int = 10,
    seed: Optional[int] = None,
) -> list[dict[str, float]]:
    """Active Failure Search 첫 라운드용 시드.

    boundary_seeds + LHS로 k개를 채운다.
    """
    boundary = sample_boundary_seeds(sg, robot_cfg)
    remaining = max(0, k - len(boundary))
    lhs = sample_latin_hypercube(sg, robot_cfg, n=remaining + 20, seed=seed)

    combined = boundary + lhs
    # 중복 제거 (근사: 유클리드 거리 < 0.01인 것 제거)
    unique: list[dict] = []
    for c in combined:
        c_vec = _params_to_unit(c)
        if not any(
            np.linalg.norm(c_vec - _params_to_unit(u)) < 0.01
            for u in unique
        ):
            unique.append(c)
        if len(unique) >= k:
            break

    return unique[:k]
