"""workspace.py — HM3D 실제 씬 위 조작 작업공간 구성 (Phase 3).

실제 스캔된 지지면(테이블 등) 위에 target/obstacle/tray를 spawn하고
로봇을 지지면 옆 받침대(pedestal) 위에 배치해, 기존 kinematic check +
6-margin oracle을 실제 씬에서 실행할 수 있게 한다.

배치 전략:
  - HM3D 테이블 상면은 0.8~1.1m — 바닥에 선 Franka(reach 0.855m)로는 높다.
    로봇 베이스를 상면보다 base_drop(0.10m) 낮은 받침대 위에 올린다.
  - 베이스 위치는 지지면 4변 중 "빈 공간이 확보된" 변의 중점 바깥쪽.
    (raycast로 받침대 자리의 수직 clearance 확인)
  - 작업 패치(target 등 spawn 영역)는 로봇 쪽 변에서 안쪽으로 reach 절반
    지점, 지지면 경계에서 margin을 두고 클리핑.

oracle 연결:
  - obstacle_body_ids = spawn한 obstacle + 작업공간 주변 HM3D chunk
    (AABB 프리필터) → collision margin이 실제 가구와의 거리로 계산됨.
  - robot_cfg는 deepcopy 후 base_position을 실제 배치 위치로 교체.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pybullet as p

from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface

from .loader import ConvertedScene, scene_extent_pybullet
from .semantics import SemanticInstance

# 작업 패치/spawn 기본 파라미터
EDGE_STANDOFF = 0.26       # 지지면 변에서 로봇 베이스까지 바깥 거리 (m, 최소값)
BASE_DROP = 0.10           # 지지면 상면 대비 베이스 높이 차 (m)
PATCH_REACH = 0.52         # 로봇 베이스에서 작업 패치 중심까지 수평 거리 (m)
SURFACE_MARGIN = 0.10      # 지지면 경계 여유 (m)
PEDESTAL_HALF_XY = 0.15    # 받침대 반폭 (m)
CHUNK_FILTER_RADIUS = 1.2  # oracle에 넘길 HM3D chunk AABB 프리필터 반경 (m)


class WorkspacePlacementError(RuntimeError):
    """지지면 주변에 로봇/패치 배치 공간이 없을 때."""


@dataclass
class HM3DWorkspace:
    """구성 완료된 작업공간."""

    surface: SemanticInstance
    robot_base_pos: list[float]
    robot_body_id: int
    pedestal_body_id: int
    body_map: dict[str, int]          # spawn 객체 {obj_id: body_id}
    sg: SceneGraph                    # 하이브리드 SceneGraph
    robot_cfg: dict                   # base_position 반영된 config
    scene_body_ids: list[int] = field(default_factory=list)
    obstacle_proxies: dict[int, SemanticInstance] = field(default_factory=dict)

    @property
    def target_pos(self) -> list[float]:
        return self.sg.target().position

    @property
    def destination_pos(self) -> list[float]:
        return self.sg.destination().position


def _edge_candidates(surface: SemanticInstance) -> list[dict]:
    """지지면 4변 주변의 (베이스 후보 위치, 안쪽 방향 단위벡터) 목록.

    식탁처럼 의자가 둘러싼 경우를 위해 변 중점만이 아니라 변을 따라
    여러 지점 × 여러 standoff 거리를 샘플링한다.
    """
    lo, hi = surface.bbox_min, surface.bbox_max
    fracs = [0.5, 0.35, 0.65, 0.2, 0.8]
    standoffs = [EDGE_STANDOFF, EDGE_STANDOFF + 0.10, EDGE_STANDOFF + 0.20]
    edges = [
        # (고정축, 고정값+방향, 가변축)
        ("x", hi[0], [-1.0, 0.0]),
        ("x", lo[0], [1.0, 0.0]),
        ("y", hi[1], [0.0, -1.0]),
        ("y", lo[1], [0.0, 1.0]),
    ]
    result = []
    for frac in fracs:
        for axis, edge_val, inward in edges:
            for so in standoffs:
                if axis == "x":
                    xy = [edge_val - inward[0] * so,
                          lo[1] + frac * (hi[1] - lo[1])]
                else:
                    xy = [lo[0] + frac * (hi[0] - lo[0]),
                          edge_val - inward[1] * so]
                result.append({"base_xy": xy, "inward": inward})
    return result


def _column_is_free(
    cid: int,
    x: float,
    y: float,
    z_lo: float,
    z_hi: float,
    half_xy: float = PEDESTAL_HALF_XY,
) -> bool:
    """(x,y) 주변 half_xy 사각 기둥 [z_lo, z_hi]가 비어 있는지 raycast로 확인.

    수직 ray만으로는 기둥과 평행한 벽면을 감지하지 못한다 (ray가 면과
    교차하지 않음). 여러 높이에서 수평 십자 ray를 함께 쏜다.
    """
    starts, ends = [], []

    # 수직 ray 5개 (기둥 모서리 + 중심)
    offsets = [(0, 0), (half_xy, half_xy), (half_xy, -half_xy),
               (-half_xy, half_xy), (-half_xy, -half_xy)]
    for dx, dy in offsets:
        starts.append([x + dx, y + dy, z_lo])
        ends.append([x + dx, y + dy, z_hi])

    # 수평 십자 ray (x방향/y방향/대각 2개) × 3개 높이
    m = half_xy * 1.3
    for t in (0.15, 0.5, 0.85):
        z = z_lo + t * (z_hi - z_lo)
        starts += [[x - m, y, z], [x, y - m, z], [x - m, y - m, z], [x - m, y + m, z]]
        ends += [[x + m, y, z], [x, y + m, z], [x + m, y + m, z], [x + m, y - m, z]]

    hits = p.rayTestBatch(starts, ends, physicsClientId=cid)
    return all(h[0] < 0 for h in hits)


def _box_intersects(
    a_lo: np.ndarray, a_hi: np.ndarray, b_lo: np.ndarray, b_hi: np.ndarray
) -> bool:
    return bool(np.all(a_lo <= b_hi) and np.all(b_lo <= a_hi))


# spawn 객체 크기 (make_workspace_objects와 공유)
TARGET_SIZE = [0.05, 0.05, 0.06]
OBSTACLE_SIZE = [0.06, 0.06, 0.10]
TRAY_SIZE = [0.16, 0.12, 0.02]
_SPAWN_CLEAR = 0.04       # spawn 객체와 기존 인스턴스 bbox 사이 최소 여유 (m)
_REACH_BAND = (0.32, 0.62)  # 베이스에서 target까지 수평 거리 허용 범위


def _spot_is_free(
    xy: np.ndarray,
    size: list[float],
    top: float,
    surface: SemanticInstance,
    proxy_instances: list[SemanticInstance],
) -> bool:
    """지지면 위 (xy)에 size 객체를 놓을 자리가 비어 있는가."""
    lo, hi = surface.bbox_min, surface.bbox_max
    hx = size[0] / 2 + _SPAWN_CLEAR
    hy = size[1] / 2 + _SPAWN_CLEAR
    # 지지면 경계 체크는 순수 half-size (여유는 객체↔객체에만 적용)
    if not (lo[0] + SURFACE_MARGIN <= xy[0] - size[0] / 2
            and xy[0] + size[0] / 2 <= hi[0] - SURFACE_MARGIN
            and lo[1] + SURFACE_MARGIN <= xy[1] - size[1] / 2
            and xy[1] + size[1] / 2 <= hi[1] - SURFACE_MARGIN):
        return False
    box_lo = np.array([xy[0] - hx, xy[1] - hy, top + 0.01])
    box_hi = np.array([xy[0] + hx, xy[1] + hy, top + max(size[2], 0.25) + 0.1])
    return not any(
        _box_intersects(box_lo, box_hi, inst.bbox_min, inst.bbox_max)
        for inst in proxy_instances
    )


def _find_patch_layout(
    base_xy: np.ndarray,
    inward: list[float],
    surface: SemanticInstance,
    proxy_instances: list[SemanticInstance],
    grid: float = 0.06,
) -> Optional[dict[str, np.ndarray]]:
    """도달 가능 영역을 그리드 탐색해 target/obstacle/tray 자리를 찾는다.

    스캔 지지면 위에는 램프/TV 등 실물이 이미 있으므로, 큰 패치 박스가
    통째로 비어 있길 요구하는 대신 객체별 footprint 단위로 빈 자리를 찾는다.

    Returns:
        {"target": xy, "obstacle": xy, "tray": xy} 또는 None.
    """
    lo, hi = surface.bbox_min, surface.bbox_max
    top = surface.top_z
    ix, iy = inward
    px_dir = np.array([ix, iy])
    perp = np.array([-iy, ix])

    xs = np.arange(lo[0] + SURFACE_MARGIN, hi[0] - SURFACE_MARGIN + 1e-9, grid)
    ys = np.arange(lo[1] + SURFACE_MARGIN, hi[1] - SURFACE_MARGIN + 1e-9, grid)
    if len(xs) == 0 or len(ys) == 0:
        return None
    gx, gy = np.meshgrid(xs, ys)
    pts = np.stack([gx.ravel(), gy.ravel()], axis=-1)

    d = np.linalg.norm(pts - base_xy, axis=1)
    band = (d >= _REACH_BAND[0]) & (d <= _REACH_BAND[1])
    cands = pts[band]
    if len(cands) == 0:
        return None
    # 선호: 중간 도달 거리 + 베이스 정면(centerline)에 가까운 순
    d_pref = np.abs(np.linalg.norm(cands - base_xy, axis=1) - 0.46)
    lateral = np.abs((cands - base_xy) @ perp)
    order = np.argsort(d_pref + 0.5 * lateral)

    for idx in order:
        t_xy = cands[idx]
        if not _spot_is_free(t_xy, TARGET_SIZE, top, surface, proxy_instances):
            continue
        # obstacle: target 옆 12cm (양쪽 시도)
        o_xy = None
        for sgn in (1.0, -1.0):
            cand_o = t_xy + perp * (0.12 * sgn)
            if _spot_is_free(cand_o, OBSTACLE_SIZE, top, surface, proxy_instances):
                o_xy = cand_o
                break
        if o_xy is None:
            continue
        # tray: 더 안쪽 / 옆쪽 / 대각 순으로 시도.
        # 도달 한계 0.70m — 상면 위 tray의 수직 오프셋(~0.13m) 포함해도
        # sqrt(0.70² + 0.13²) = 0.71 < max_reach 0.855 (여유 14cm).
        tray_xy = None
        tray_offsets = (
            px_dir * 0.20, -perp * 0.22, perp * 0.22,
            px_dir * 0.18 - perp * 0.16, px_dir * 0.18 + perp * 0.16,
            px_dir * 0.26,
        )
        for off in tray_offsets:
            cand_t = t_xy + off
            if float(np.linalg.norm(cand_t - base_xy)) > 0.70:
                continue
            if np.linalg.norm(cand_t - o_xy) < 0.14:
                continue  # obstacle과 겹침 방지
            if _spot_is_free(cand_t, TRAY_SIZE, top, surface, proxy_instances):
                tray_xy = cand_t
                break
        if tray_xy is None:
            continue
        return {"target": t_xy, "obstacle": o_xy, "tray": tray_xy}
    return None


def choose_robot_base(
    cid: int,
    surface: SemanticInstance,
    floor_z: float,
    lo: np.ndarray,
    hi: np.ndarray,
    proxy_instances: list[SemanticInstance],
) -> dict:
    """베이스 기둥과 작업 패치가 모두 확보되는 배치를 고른다.

    검사 3종:
      1. 기둥 raycast (실제 mesh — 수직 + 수평 십자)
      2. 기둥 box vs 주변 인스턴스 bbox 교차 (proxy와 일관된 기준)
      3. 패치 검증: 도달 거리 유지 + 패치 위(상면~+0.45m)로 솟은 인스턴스 없음
         (예: 테이블 밑에 밀어넣은 의자 등받이가 상면 위로 나온 경우)
         변 방향 오프셋 5개를 시도해 빈 구역을 찾는다.

    Returns:
        {"base_pos": [x,y,z], "inward": [ix,iy], "patch_xy": ndarray}

    Raises:
        WorkspacePlacementError: 모든 후보 탈락 (사유 카운트 포함).
    """
    base_z = surface.top_z - BASE_DROP
    fail_counts = {"bounds": 0, "raycast": 0, "column_bbox": 0, "patch": 0}

    for cand in _edge_candidates(surface):
        x, y = cand["base_xy"]
        if not (lo[0] + 0.2 < x < hi[0] - 0.2 and lo[1] + 0.2 < y < hi[1] - 0.2):
            fail_counts["bounds"] += 1
            continue

        # 1) 기둥 raycast (mesh)
        if not _column_is_free(cid, x, y, floor_z + 0.05, base_z + 0.9):
            fail_counts["raycast"] += 1
            continue

        # 2) 기둥 box vs 인스턴스 bbox
        m = PEDESTAL_HALF_XY + 0.03
        col_lo = np.array([x - m, y - m, floor_z + 0.05])
        col_hi = np.array([x + m, y + m, base_z + 0.9])
        if any(
            _box_intersects(col_lo, col_hi, inst.bbox_min, inst.bbox_max)
            for inst in proxy_instances
        ):
            fail_counts["column_bbox"] += 1
            continue

        # 3) 객체 레이아웃 탐색 (그리드 — 상면 위 실물 사이 빈 자리)
        layout = _find_patch_layout(
            np.array([x, y]), cand["inward"], surface, proxy_instances
        )
        if layout is None:
            fail_counts["patch"] += 1
            continue
        return {
            "base_pos": [x, y, base_z],
            "inward": cand["inward"],
            "layout": layout,
        }

    raise WorkspacePlacementError(
        f"지지면 #{surface.instance_id} ({surface.category}) 배치 실패 — "
        f"후보 탈락 사유: {fail_counts}"
    )


def _spawn_pedestal(cid: int, base_pos: list[float], floor_z: float) -> int:
    """로봇 받침대 기둥 (static)."""
    height = base_pos[2] - floor_z
    half = [PEDESTAL_HALF_XY, PEDESTAL_HALF_XY, height / 2]
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=cid)
    vis = p.createVisualShape(
        p.GEOM_BOX, halfExtents=half, rgbaColor=[0.35, 0.35, 0.38, 1.0],
        physicsClientId=cid,
    )
    return p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=col,
        baseVisualShapeIndex=vis,
        basePosition=[base_pos[0], base_pos[1], floor_z + height / 2],
        physicsClientId=cid,
    )


def make_workspace_objects(
    surface: SemanticInstance,
    layout: dict[str, np.ndarray],
) -> list[ObjectNode]:
    """_find_patch_layout이 찾은 자리에 target / obstacle / tray를 만든다."""
    top = surface.top_z

    def at(xy: np.ndarray, sz: list[float]) -> list[float]:
        return [float(xy[0]), float(xy[1]), top + sz[2] / 2]

    return [
        ObjectNode(
            id="target_block", role=Role.TARGET,
            position=at(layout["target"], TARGET_SIZE), size=list(TARGET_SIZE),
            movable=True, shape="block",
        ),
        ObjectNode(
            id="obstacle_block", role=Role.OBSTACLE,
            position=at(layout["obstacle"], OBSTACLE_SIZE), size=list(OBSTACLE_SIZE),
            movable=True, shape="block",
        ),
        ObjectNode(
            id="tray", role=Role.DESTINATION,
            position=at(layout["tray"], TRAY_SIZE), size=list(TRAY_SIZE),
            movable=False, shape="tray",
        ),
    ]


# proxy에서 제외할 카테고리 (바닥/천장은 작업 높이대와 무관)
PROXY_EXCLUDE_CATEGORIES = {"floor", "ceiling", "rug", "carpet", "mat"}

# 구조물 카테고리: 여러 평면 세그먼트가 하나의 인스턴스로 묶이는 경우가 있어
# (L자 벽, ㄷ자 door frame 등) AABB가 방 내부를 통째로 덮으면 proxy로 부적합
_PLANAR_CATEGORIES = {
    "wall", "window", "door", "curtain", "blinds", "mirror",
    "door frame", "doorframe", "window frame", "door way", "doorway",
}
_PLANAR_MAX_THIN = 0.60  # 얇은 변이 이보다 크면 복합 세그먼트로 보고 제외


def proxy_candidate_instances(
    instances: list[SemanticInstance],
    surface: SemanticInstance,
    floor_z: float,
    radius: float = CHUNK_FILTER_RADIUS,
) -> list[SemanticInstance]:
    """oracle 거리 쿼리에 쓸 주변 인스턴스를 고른다 (지지면 중심 기준).

    지지면 인스턴스 자체는 제외 (Track A에서 테이블은 충돌 대상이 아님).
    복합 평면 구조물(L자 벽, ㄷ자 door frame)은 AABB가 실내를 통째로
    덮으므로 제외하고, 얇은 단일 세그먼트(예: 0.14×3.5m 벽)는 유지한다.
    """
    center = surface.center[:2]
    reach_pad = radius + PATCH_REACH + float(max(surface.size[:2])) / 2
    z_lo = floor_z + 0.05
    z_hi = surface.top_z + 1.0

    result = []
    for inst in instances:
        if inst.instance_id == surface.instance_id:
            continue
        if inst.category in PROXY_EXCLUDE_CATEGORIES:
            continue
        if (inst.category in _PLANAR_CATEGORIES
                and min(inst.size[0], inst.size[1]) > _PLANAR_MAX_THIN):
            continue
        if (inst.bbox_max[0] < center[0] - reach_pad
                or inst.bbox_min[0] > center[0] + reach_pad
                or inst.bbox_max[1] < center[1] - reach_pad
                or inst.bbox_min[1] > center[1] + reach_pad):
            continue
        if inst.bbox_max[2] < z_lo or inst.bbox_min[2] > z_hi:
            continue
        result.append(inst)
    return result


def spawn_obstacle_proxies(
    cid: int,
    proxy_instances: list[SemanticInstance],
) -> dict[int, SemanticInstance]:
    """인스턴스 AABB를 invisible collision box body로 spawn한다.

    이유: PyBullet에서 concave trimesh(GEOM_FORCE_CONCAVE_TRIMESH)에 대한
    getClosestPoints 거리 쿼리는 쓰레기 값을 반환한다 (00800에서 -3e+288 확인).
    → 거리 기반 oracle margin은 인스턴스 AABB proxy box로 계산하고,
    HM3D mesh는 렌더링/raycast 전용으로 남긴다 (계획 D-5).

    Returns:
        {proxy_body_id: SemanticInstance}
    """
    proxies: dict[int, SemanticInstance] = {}
    for inst in proxy_instances:
        col = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=(inst.size / 2.0).tolist(),
            physicsClientId=cid,
        )
        bid = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=col,
            basePosition=inst.center.tolist(),  # base pos = 인스턴스 중심 (clearance 계산에 사용됨)
            physicsClientId=cid,
        )
        proxies[bid] = inst
    return proxies


def build_hybrid_scene_graph(
    scene_id: str,
    surface: SemanticInstance,
    spawned: list[ObjectNode],
    instances: list[SemanticInstance],
    context_radius: float = 1.5,
) -> SceneGraph:
    """spawn 객체 + 주변 HM3D 인스턴스(컨텍스트)로 하이브리드 SceneGraph 구성."""
    surf_node = SupportSurface(
        id=f"hm3d_{surface.instance_id:04d}_{surface.category.replace(' ', '_')}",
        type="plane",
        height=surface.top_z,
        bounds={
            "x": [float(surface.bbox_min[0]), float(surface.bbox_max[0])],
            "y": [float(surface.bbox_min[1]), float(surface.bbox_max[1])],
        },
    )

    objects = list(spawned)
    center = surface.center[:2]
    for inst in instances:
        if inst.instance_id == surface.instance_id:
            continue
        if float(np.linalg.norm(inst.center[:2] - center)) > context_radius:
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
                    "hm3d_instance_id": inst.instance_id,
                    "hm3d_context": True,  # PyBullet body 별도 spawn 안 함
                },
            )
        )

    return SceneGraph(
        scene_id=scene_id,
        support_surfaces=[surf_node],
        objects=objects,
        meta={
            "source": "hm3d_workspace",
            "surface_instance_id": surface.instance_id,
            "surface_category": surface.category,
        },
    )


def setup_workspace(
    converted: ConvertedScene,
    scene_body_ids: list[int],
    surface: SemanticInstance,
    instances: list[SemanticInstance],
    floor_z: float,
    robot_cfg: dict,
    cid: int,
) -> HM3DWorkspace:
    """HM3D 씬(로드 완료 상태)에 작업공간을 구성한다.

    호출 전: load_hm3d_static(collision=True) 완료, floor_z 추정 완료.
    이후 sim_runner.run_kinematic_check / physical_oracle.evaluate에 바로
    연결할 수 있는 상태를 반환한다.
    """
    import scene_builder
    import sim_runner

    lo, hi = scene_extent_pybullet(converted)
    proxy_instances = proxy_candidate_instances(instances, surface, floor_z)
    choice = choose_robot_base(cid, surface, floor_z, lo, hi, proxy_instances)
    base_pos = choice["base_pos"]

    pedestal_id = _spawn_pedestal(cid, base_pos, floor_z)

    # 로봇 로드 (base_position 교체한 config)
    cfg = copy.deepcopy(robot_cfg)
    cfg["robot"]["base_position"] = base_pos
    scene_builder._client_id = cid  # 기존 모듈들의 공유 client 사용
    sim_runner._ROBOT_BODY_ID = None
    robot_id = sim_runner.load_robot(cfg)

    # 객체 spawn
    spawned_nodes = make_workspace_objects(surface, choice["layout"])
    body_map: dict[str, int] = {}
    for node in spawned_nodes:
        body_map[node.id] = scene_builder._spawn_object(node)

    sg = build_hybrid_scene_graph(
        scene_id=f"hm3d_{converted.scene_dir}",
        surface=surface,
        spawned=spawned_nodes,
        instances=instances,
    )

    proxies = spawn_obstacle_proxies(cid, proxy_instances)

    return HM3DWorkspace(
        surface=surface,
        robot_base_pos=base_pos,
        robot_body_id=robot_id,
        pedestal_body_id=pedestal_id,
        body_map=body_map,
        sg=sg,
        robot_cfg=cfg,
        scene_body_ids=scene_body_ids,
        obstacle_proxies=proxies,
    )


def run_case(workspace: HM3DWorkspace, thresholds: dict):
    """kinematic check + 6-margin oracle 실행 → OracleResult.

    obstacle = spawn한 obstacle_block + 주변 인스턴스 AABB proxy.
    proxy의 basePosition은 인스턴스 중심이므로 clearance/goal margin의
    수평 거리 근사도 Track A와 같은 의미로 동작한다.
    받침대는 로봇 지지 구조물이므로 obstacle에서 제외.
    """
    import physical_oracle
    import sim_runner

    obstacle_ids = (
        [workspace.body_map["obstacle_block"]]
        + list(workspace.obstacle_proxies.keys())
    )

    kin = sim_runner.run_kinematic_check(
        target_pos=workspace.target_pos,
        destination_pos=workspace.destination_pos,
        obstacle_body_ids=obstacle_ids,
        human_zone_body_ids=[],
        destination_body_id=workspace.body_map["tray"],
        robot_body_id=workspace.robot_body_id,
        robot_cfg=workspace.robot_cfg,
    )
    return physical_oracle.evaluate(
        kin, workspace.sg, workspace.robot_cfg, thresholds
    ), kin
