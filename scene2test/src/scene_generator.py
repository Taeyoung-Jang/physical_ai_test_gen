"""scene_generator.py — Track A 절차적 Base Scene 생성기.

핵심 불변 조건:
  생성된 모든 base scene은 nominal PASS (mutation 없이 로봇이 성공할 수 있는 상태).
  실패는 Mutation Space Builder가 만들어내며, 생성기는 그 전제 조건을 보장한다.

주요 함수:
  generate_scene(seed, scene_cfg, robot_cfg)  → SceneGraph
  generate_library(n, scene_cfg, robot_cfg, output_dir)  → List[SceneGraph]
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface, UnknownRegion
from validity import is_valid_base_scene, objects_overlap, point_in_bounds


# ---------------------------------------------------------------------------
# 설정 로더
# ---------------------------------------------------------------------------

def load_scene_config(path: str = "config/scene_gen_config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_robot_config(path: str = "config/robot_config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _rand_in(rng: np.random.Generator, lo: float, hi: float) -> float:
    return float(rng.uniform(lo, hi))


def _rand_size(rng: np.random.Generator, size_range: dict) -> list[float]:
    sx = _rand_in(rng, *size_range["x"])
    sy = _rand_in(rng, *size_range["y"])
    sz = _rand_in(rng, *size_range["z"])
    return [round(sx, 4), round(sy, 4), round(sz, 4)]


def _surface_z(surf_height: float, obj_size_z: float) -> float:
    """객체 중심 z: 지지면 위에 정확히 올라가도록 계산한다."""
    return surf_height + obj_size_z / 2


def _place_on_surface(
    rng: np.random.Generator,
    size: list[float],
    bounds: dict,
    margin: float = 0.01,
) -> Optional[list[float]]:
    """지지면 위에 랜덤 XY 위치를 반환한다. margin을 고려해 경계에서 안쪽에 배치."""
    half_x = size[0] / 2 + margin
    half_y = size[1] / 2 + margin
    x_lo = bounds["x"][0] + half_x
    x_hi = bounds["x"][1] - half_x
    y_lo = bounds["y"][0] + half_y
    y_hi = bounds["y"][1] - half_y
    if x_lo >= x_hi or y_lo >= y_hi:
        return None
    x = _rand_in(rng, x_lo, x_hi)
    y = _rand_in(rng, y_lo, y_hi)
    return [round(x, 4), round(y, 4)]


def _place_in_annulus(
    rng: np.random.Generator,
    robot_base: list[float],
    max_reach: float,
    r_min_frac: float,
    r_max_frac: float,
    bounds: dict,
    size: list[float],
    max_tries: int = 200,
) -> Optional[list[float]]:
    """로봇 도달 가능 환형 영역(annulus) 내 XY 위치를 반환한다."""
    r_lo = max_reach * r_min_frac
    r_hi = max_reach * r_max_frac
    half = np.array(size[:2]) / 2

    for _ in range(max_tries):
        r = _rand_in(rng, r_lo, r_hi)
        theta = _rand_in(rng, 0, 2 * math.pi)
        x = robot_base[0] + r * math.cos(theta)
        y = robot_base[1] + r * math.sin(theta)

        # bounds 안에 있는지 확인
        if (bounds["x"][0] + half[0] <= x <= bounds["x"][1] - half[0] and
                bounds["y"][0] + half[1] <= y <= bounds["y"][1] - half[1]):
            return [round(x, 4), round(y, 4)]
    return None


def _no_overlap_position(
    rng: np.random.Generator,
    size: list[float],
    bounds: dict,
    existing: list[ObjectNode],
    min_gap: float = 0.05,
    max_tries: int = 200,
) -> Optional[list[float]]:
    """기존 객체들과 겹치지 않는 XY 위치를 rejection sampling으로 찾는다."""
    half = np.array(size[:2]) / 2

    for _ in range(max_tries):
        xy = _place_on_surface(rng, size, bounds)
        if xy is None:
            continue
        cx, cy = xy
        ok = True
        for obj in existing:
            if obj.role == Role.HUMAN_ZONE:
                continue
            ex, ey = obj.position[:2]
            ex_half = np.array(obj.size[:2]) / 2
            # AABB 간격 검사
            gap_x = abs(cx - ex) - (half[0] + ex_half[0])
            gap_y = abs(cy - ey) - (half[1] + ex_half[1])
            if gap_x < min_gap and gap_y < min_gap:
                ok = False
                break
        if ok:
            return [round(cx, 4), round(cy, 4)]
    return None


# ---------------------------------------------------------------------------
# 개별 요소 생성
# ---------------------------------------------------------------------------

def _make_target(
    rng: np.random.Generator,
    cfg: dict,
    robot_cfg: dict,
    bounds: dict,
    surf_height: float,
    existing: list[ObjectNode],
    obj_idx: int,
) -> Optional[ObjectNode]:
    size = _rand_size(rng, cfg["target"]["size_range"])
    rf = cfg["target"]["reach_fraction"]
    xy = _place_in_annulus(
        rng,
        robot_cfg["robot"]["base_position"],
        robot_cfg["robot"]["max_reach"],
        rf[0], rf[1],
        bounds, size,
        cfg["validity"]["max_placement_attempts"],
    )
    if xy is None:
        return None
    shape = rng.choice(cfg["target"]["types"])
    pos = [xy[0], xy[1], _surface_z(surf_height, size[2])]
    return ObjectNode(
        id=f"target_{obj_idx}",
        role=Role.TARGET,
        position=pos,
        size=size,
        movable=True,
        shape=str(shape),
    )


def _make_obstacle(
    rng: np.random.Generator,
    cfg: dict,
    bounds: dict,
    surf_height: float,
    existing: list[ObjectNode],
    obj_idx: int,
) -> Optional[ObjectNode]:
    size = _rand_size(rng, cfg["obstacles"]["size_range"])
    min_gap = cfg["obstacles"]["min_gap_to_target"]
    xy = _no_overlap_position(rng, size, bounds, existing, min_gap=min_gap,
                               max_tries=cfg["validity"]["max_placement_attempts"])
    if xy is None:
        return None
    shape = str(rng.choice(cfg["obstacles"]["types"]))
    pos = [xy[0], xy[1], _surface_z(surf_height, size[2])]
    return ObjectNode(
        id=f"obstacle_{obj_idx}",
        role=Role.OBSTACLE,
        position=pos,
        size=size,
        movable=True,
        shape=shape,
    )


def _make_destination(
    rng: np.random.Generator,
    cfg: dict,
    bounds: dict,
    surf_height: float,
    existing: list[ObjectNode],
    obj_idx: int,
) -> Optional[ObjectNode]:
    size = _rand_size(rng, cfg["destination"]["size_range"])
    # 기존 객체와 겹치지 않게, table 안에 배치
    xy = _no_overlap_position(rng, size, bounds, existing, min_gap=0.05,
                               max_tries=cfg["validity"]["max_placement_attempts"])
    if xy is None:
        return None
    shape = str(rng.choice(cfg["destination"]["types"]))
    pos = [xy[0], xy[1], _surface_z(surf_height, size[2])]
    return ObjectNode(
        id=f"destination_{obj_idx}",
        role=Role.DESTINATION,
        position=pos,
        size=size,
        movable=False,
        shape=shape,
    )


def _make_human_zone(
    rng: np.random.Generator,
    cfg: dict,
    bounds: dict,
    existing: list[ObjectNode],
    obj_idx: int,
    robot_base: list[float] = (0.0, 0.0, 0.0),
) -> Optional[ObjectNode]:
    """human_zone을 robot_base→target 경로 선분에서 충분히 떨어진 곳에 배치한다."""
    radius = _rand_in(rng, *cfg["human_zone"]["radius_range"])
    min_dist = cfg["human_zone"]["min_dist_to_path"]

    target_nodes = [o for o in existing if o.role == Role.TARGET]
    t_pos = np.array(target_nodes[0].position[:2]) if target_nodes else np.array([0.5, 0.0])
    r_base = np.array(robot_base[:2])
    seg = t_pos - r_base
    seg_len_sq = float(np.dot(seg, seg))

    size = [radius * 2, radius * 2, 1.80]
    for _ in range(cfg["validity"]["max_placement_attempts"]):
        xy = _place_on_surface(rng, size, bounds, margin=radius)
        if xy is None:
            continue
        pt = np.array(xy)

        # 경로 선분 r_base→t_pos 에 대한 최소 거리 계산
        if seg_len_sq > 1e-12:
            t_val = float(np.dot(pt - r_base, seg)) / seg_len_sq
            t_val = max(0.0, min(1.0, t_val))
            proj = r_base + t_val * seg
            dist_to_path = float(np.linalg.norm(pt - proj)) - radius
        else:
            dist_to_path = float(np.linalg.norm(pt - r_base)) - radius

        if dist_to_path >= min_dist:
            pos = [xy[0], xy[1], 0.0]
            return ObjectNode(
                id=f"human_zone_{obj_idx}",
                role=Role.HUMAN_ZONE,
                position=pos,
                size=size,
                movable=False,
                shape="cylinder",
                extra={"radius": radius},
            )
    return None


# ---------------------------------------------------------------------------
# 관계 계산
# ---------------------------------------------------------------------------

def _build_relations(sg: SceneGraph) -> list:
    """SceneGraph 내 객체 쌍의 거리 기반 관계를 계산한다."""
    from scene_graph import Relation
    relations = []
    objects = sg.objects
    target = sg.target()
    robot_base = [0.0, 0.0, 0.0]  # 기본값; robot_cfg 없이도 동작

    for obj in objects:
        if obj.role in (Role.OBSTACLE, Role.DISTRACTOR) and target:
            dist = float(np.linalg.norm(
                np.array(obj.position[:2]) - np.array(target.position[:2])
            ))
            rel_type = "near" if dist < 0.15 else "far"
            relations.append(Relation(rel_type, obj.id, target.id, distance_m=round(dist, 4)))

    if target:
        dist_to_robot = float(np.linalg.norm(np.array(target.position) - np.array(robot_base)))
        max_reach = 0.855
        relations.append(Relation(
            "reachable", "panda_arm", target.id,
            value=bool(dist_to_robot <= max_reach)
        ))

    return relations


# ---------------------------------------------------------------------------
# 메인 생성 함수
# ---------------------------------------------------------------------------

def generate_scene(
    seed: int,
    scene_cfg: Optional[dict] = None,
    robot_cfg: Optional[dict] = None,
) -> Optional[SceneGraph]:
    """seed를 사용해 재현 가능한 base scene을 생성한다.

    모든 생성 시도가 실패하면 None을 반환한다.
    """
    scene_cfg = scene_cfg or load_scene_config()
    robot_cfg = robot_cfg or load_robot_config()
    cfg = scene_cfg["scene_generation"]

    rng = np.random.default_rng(seed)

    # 1. workspace (table bounds) 결정
    surf_height = cfg["workspace"]["table_height"]
    x_edge = cfg["workspace"]["table_x_range"]
    y_half_range = cfg["workspace"]["table_y_halfwidth"]
    x_min = _rand_in(rng, x_edge[0][0], x_edge[0][1])
    x_max = _rand_in(rng, x_edge[1][0], x_edge[1][1])
    y_half = _rand_in(rng, *y_half_range)
    bounds = {
        "x": [round(x_min, 3), round(x_max, 3)],
        "y": [round(-y_half, 3), round(y_half, 3)],
    }
    support_surface = SupportSurface(
        id="table_1", type="plane", height=surf_height, bounds=bounds
    )

    existing: list[ObjectNode] = []

    # 2. target (필수)
    target = _make_target(rng, cfg, robot_cfg, bounds, surf_height, existing, 0)
    if target is None:
        return None
    existing.append(target)

    # 3. obstacles (0~N개)
    n_obs = int(rng.integers(cfg["obstacles"]["count_range"][0],
                              cfg["obstacles"]["count_range"][1] + 1))
    for i in range(n_obs):
        obs = _make_obstacle(rng, cfg, bounds, surf_height, existing, i)
        if obs:
            existing.append(obs)

    # 4. destination (필수)
    destination = _make_destination(rng, cfg, bounds, surf_height, existing, 0)
    if destination is None:
        return None
    existing.append(destination)

    # 5. human_zone (확률적)
    if rng.random() < cfg["human_zone"]["presence_prob"]:
        hz = _make_human_zone(rng, cfg, bounds, existing, 0,
                              robot_base=robot_cfg["robot"]["base_position"])
        if hz:
            existing.append(hz)

    # SceneGraph 조립
    sg = SceneGraph(
        scene_id=f"scene_{seed:05d}",
        support_surfaces=[support_surface],
        objects=existing,
        meta={
            "source": "procedural",
            "seed": seed,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    sg.relations = _build_relations(sg)

    # 유효성 최종 검증
    if not is_valid_base_scene(sg, robot_cfg, verbose=False):
        return None

    return sg


# ---------------------------------------------------------------------------
# 라이브러리 생성
# ---------------------------------------------------------------------------

def generate_library(
    n: int = 20,
    output_dir: str = "data/scene_library",
    scene_cfg: Optional[dict] = None,
    robot_cfg: Optional[dict] = None,
    base_seed: int = 0,
) -> list[SceneGraph]:
    """n개의 유효한 base scene을 생성해 output_dir에 저장한다.

    실패한 seed는 건너뛰고 n개가 채워질 때까지 시도한다.
    """
    scene_cfg = scene_cfg or load_scene_config()
    robot_cfg = robot_cfg or load_robot_config()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    library: list[SceneGraph] = []
    seed = base_seed
    attempts = 0
    max_attempts = n * 20  # 최대 시도 횟수

    print(f"Scene 라이브러리 생성 중 (목표: {n}개) ...")
    while len(library) < n and attempts < max_attempts:
        sg = generate_scene(seed, scene_cfg, robot_cfg)
        if sg is not None:
            path = out / f"{sg.scene_id}.json"
            sg.save(str(path))
            library.append(sg)
            print(f"  [{len(library):2d}/{n}] {sg.scene_id}  "
                  f"objects={len(sg.objects)}  seed={seed}")
        seed += 1
        attempts += 1

    if len(library) < n:
        print(f"  경고: {attempts}번 시도 후 {len(library)}개만 생성됨")
    else:
        print(f"  완료: {len(library)}개 → {out}/")

    return library


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scene 라이브러리 생성")
    parser.add_argument("--n", type=int, default=20, help="생성할 scene 수")
    parser.add_argument("--output-dir", default="data/scene_library")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    scenes = generate_library(args.n, args.output_dir, base_seed=args.seed)
    print(f"\n생성 완료: {len(scenes)}개")
