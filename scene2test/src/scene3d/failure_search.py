"""failure_search.py — Active Failure Search를 로드된 3D scene 위에서 실행.

기존 탐색 엔진(surrogate + acquisition + 라운드 루프, active_failure_search.py)
은 그대로 재사용하고, 평가 경로만 교체한다:

  절차적 씬(scene_builder): 매 테스트 reset_simulation + 씬 재구성 (가벼워서 가능)
  로드된 3D scene         : 씬(chunk 수백 개, 로드에 수 초~수십 초)을 1회만
                           로드하고, mutation은 spawn된 body들의 teleport로
                           적용 (테스트당 ~0.1s)

좌표계 전략:
  탐색 엔진(mutation 샘플러, validity, feature extractor)은 "로봇 베이스 =
  원점, 작업 방향 = +x"를 전제한다. workspace_setup의 배치 inward 방향은
  항상 축정렬(±x/±y)이므로, 하이브리드 SceneGraph를 **로봇-로컬 프레임**으로
  회전/평행이동해 넘기면 엔진 전체가 무수정으로 동작한다. 평가 시에만
  mutation 결과 위치를 월드 프레임으로 역변환해 body를 옮긴다.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np
import pybullet as p

import physical_oracle
import scene_builder
import sim_runner
from active_failure_search import ActiveFailureSearch, SearchConfig
from physical_oracle import OracleResult
from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface

from .workspace_setup import SceneWorkspace

# 미사용 body 주차 위치 (씬 밖 멀리)
_PARK_POS = [500.0, 500.0, -50.0]


# ---------------------------------------------------------------------------
# 로봇-로컬 프레임 (축정렬 회전만)
# ---------------------------------------------------------------------------

@dataclass
class LocalFrame:
    """월드 ↔ 로봇-로컬 좌표 변환. 회전은 0/90/180/270° 중 하나."""

    base_xy: np.ndarray   # 월드 로봇 베이스 (x, y)
    base_z: float         # 월드 로봇 베이스 z
    theta: float          # 로컬 +x가 가리키는 월드 방향 (rad, 축정렬)

    @classmethod
    def from_workspace(cls, ws: SceneWorkspace) -> "LocalFrame":
        base = np.array(ws.robot_base_pos)
        target = np.array(ws.target_pos)
        inward = target[:2] - base[:2]
        # 축정렬 방향으로 스냅
        theta = round(math.atan2(inward[1], inward[0]) / (math.pi / 2)) * (math.pi / 2)
        return cls(base_xy=base[:2], base_z=float(base[2]), theta=float(theta))

    @property
    def _rot(self) -> np.ndarray:
        c, s = math.cos(self.theta), math.sin(self.theta)
        return np.array([[c, -s], [s, c]])

    def to_local(self, pos_world: list[float]) -> list[float]:
        xy = self._rot.T @ (np.array(pos_world[:2]) - self.base_xy)
        return [float(xy[0]), float(xy[1]), float(pos_world[2] - self.base_z)]

    def to_world(self, pos_local: list[float]) -> list[float]:
        xy = self.base_xy + self._rot @ np.array(pos_local[:2])
        return [float(xy[0]), float(xy[1]), float(pos_local[2] + self.base_z)]

    def size_to_local(self, size: list[float]) -> list[float]:
        """축정렬 90/270° 회전이면 x/y 크기를 교환한다."""
        if abs(math.sin(self.theta)) > 0.5:
            return [size[1], size[0], size[2]]
        return list(size)


def build_local_scene_graph(ws: SceneWorkspace, frame: LocalFrame) -> SceneGraph:
    """하이브리드 SceneGraph → 로봇-로컬 프레임 + tray 점유용 occupant 노드 추가.

    apply_mutation의 tray_occupied는 obstacles()[1]을 tray 위로 옮기므로,
    두 번째 movable obstacle(occupant_block)을 컨텍스트 노드보다 앞에 넣는다.
    """
    surf_w = ws.sg.support_surfaces[0]
    # bounds 코너를 로컬로 회전 후 재-AABB (축정렬이라 정확)
    corners = [
        frame.to_local([x, y, surf_w.height])
        for x in surf_w.bounds["x"] for y in surf_w.bounds["y"]
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    surf_l = SupportSurface(
        id=surf_w.id,
        type=surf_w.type,
        height=float(surf_w.height - frame.base_z),
        bounds={"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]},
    )

    spawned: list[ObjectNode] = []
    context: list[ObjectNode] = []
    for obj in ws.sg.objects:
        node = copy.deepcopy(obj)
        node.position = frame.to_local(obj.position)
        node.size = frame.size_to_local(obj.size)
        (context if obj.extra.get("hm3d_context") else spawned).append(node)

    # tray 점유용 두 번째 movable obstacle (초기엔 주차 상태)
    occupant = ObjectNode(
        id="occupant_block",
        role=Role.OBSTACLE,
        position=frame.to_local(_PARK_POS),
        size=[0.06, 0.06, 0.06],
        movable=True,
        shape="block",
    )
    # obstacles() 순서 보장: [obstacle_block, occupant_block, ...context]
    ordered = sorted(spawned, key=lambda o: 0 if o.role == Role.OBSTACLE else 1)
    objects = ordered[:1] + [occupant] + ordered[1:] + context

    return SceneGraph(
        scene_id=f"{ws.sg.scene_id}_local",
        support_surfaces=[surf_l],
        objects=objects,
        meta=dict(ws.sg.meta, frame="robot_local"),
    )


# ---------------------------------------------------------------------------
# 탐색 세션 (씬 1회 로드 + teleport 평가)
# ---------------------------------------------------------------------------

@dataclass
class SceneSearchSession:
    """로드 완료된 3D scene + 탐색에 필요한 body 핸들."""

    ws: SceneWorkspace
    cid: int
    frame: LocalFrame
    local_sg: SceneGraph
    occupant_body: int
    human_zone_body: int
    _initial_pos: dict[int, list[float]] = field(default_factory=dict)

    @classmethod
    def create(cls, ws: SceneWorkspace, cid: int) -> "SceneSearchSession":
        frame = LocalFrame.from_workspace(ws)
        local_sg = build_local_scene_graph(ws, frame)

        scene_builder._client_id = cid
        occupant = scene_builder.create_box(
            list(_PARK_POS), [0.03, 0.03, 0.03],
            color=[0.55, 0.35, 0.15, 1.0], mass=0.1,
        )
        hz = scene_builder.create_human_zone(list(_PARK_POS[:2]) + [0.0], radius=0.15)

        session = cls(
            ws=ws, cid=cid, frame=frame, local_sg=local_sg,
            occupant_body=occupant, human_zone_body=hz,
        )
        for key in ("target_block", "obstacle_block", "tray"):
            bid = ws.body_map[key]
            pos, _ = p.getBasePositionAndOrientation(bid, physicsClientId=cid)
            session._initial_pos[bid] = list(pos)
        return session

    # ── body 이동 ────────────────────────────────────────────────────────

    def _move(self, body_id: int, pos_world: list[float]) -> None:
        p.resetBasePositionAndOrientation(
            body_id, pos_world, [0, 0, 0, 1], physicsClientId=self.cid
        )

    def apply_mutation_world(self, mutated_local: SceneGraph) -> dict:
        """mutation이 반영된 로컬 SceneGraph를 월드 body로 반영한다.

        Returns:
            {"target_pos", "dest_pos", "obstacle_ids", "hz_ids", "occ_ratio"}
        """
        ws = self.ws
        target = mutated_local.target()
        dest = mutated_local.destination()
        obstacles = mutated_local.obstacles()

        t_world = self.frame.to_world(target.position)
        d_world = self.frame.to_world(dest.position)
        self._move(ws.body_map["target_block"], t_world)
        self._move(ws.body_map["tray"], d_world)

        # obstacle_block (obstacles[0])
        o_world = self.frame.to_world(obstacles[0].position)
        self._move(ws.body_map["obstacle_block"], o_world)

        # occupant_block (obstacles[1]) — tray_occupied가 아니면 주차 위치 그대로
        occ_local = obstacles[1].position
        occ_world = (
            self.frame.to_world(occ_local)
            if occ_local[0] < 400.0  # 주차 상태(원거리)면 이동 생략
            else list(_PARK_POS)
        )
        self._move(self.occupant_body, occ_world)

        # human zone
        hz_nodes = mutated_local.human_zones()
        hz_ids: list[int] = []
        if hz_nodes:
            hz_world = self.frame.to_world(hz_nodes[0].position)
            self._move(self.human_zone_body, [hz_world[0], hz_world[1], 0.9])
            hz_ids = [self.human_zone_body]
        else:
            self._move(self.human_zone_body, list(_PARK_POS))

        occ_ratio = 0.0
        if mutated_local.unknown_regions:
            occ_ratio = mutated_local.unknown_regions[0].occlusion_ratio

        obstacle_ids = (
            [ws.body_map["obstacle_block"], self.occupant_body]
            + list(ws.obstacle_proxies.keys())
        )
        return {
            "target_pos": t_world,
            "dest_pos": d_world,
            "obstacle_ids": obstacle_ids,
            "hz_ids": hz_ids,
            "occ_ratio": occ_ratio,
        }

    def restore(self) -> None:
        """spawn body들을 초기 레이아웃으로 되돌린다."""
        for bid, pos in self._initial_pos.items():
            self._move(bid, pos)
        self._move(self.occupant_body, list(_PARK_POS))
        self._move(self.human_zone_body, list(_PARK_POS))


# ---------------------------------------------------------------------------
# 탐색 클래스: 평가만 교체
# ---------------------------------------------------------------------------

def _local_robot_cfg(robot_cfg: dict) -> dict:
    cfg = copy.deepcopy(robot_cfg)
    cfg["robot"]["base_position"] = [0.0, 0.0, 0.0]
    return cfg


class SceneFailureSearch(ActiveFailureSearch):
    """HM3D 씬 위 Active Failure Search.

    탐색 측(샘플링/feature/surrogate/acquisition)은 로봇-로컬 SceneGraph로
    부모 클래스가 그대로 수행하고, _evaluate만 teleport + kinematic check로
    교체한다.
    """

    def __init__(
        self,
        session: SceneSearchSession,
        thresholds: dict,
        config: SearchConfig,
        pretrained_surrogate=None,
    ):
        self.session = session
        super().__init__(
            scene_graph=session.local_sg,
            robot_cfg=_local_robot_cfg(session.ws.robot_cfg),
            thresholds=thresholds,
            config=config,
            pretrained_surrogate=pretrained_surrogate,
        )

    def _evaluate(self, params: dict, test_id: str) -> OracleResult:
        sess = self.session
        mutated_local = scene_builder.apply_mutation(self.sg, params)
        world = sess.apply_mutation_world(mutated_local)

        kin = sim_runner.run_kinematic_check(
            target_pos=world["target_pos"],
            destination_pos=world["dest_pos"],
            obstacle_body_ids=world["obstacle_ids"],
            human_zone_body_ids=world["hz_ids"],
            destination_body_id=sess.ws.body_map["tray"],
            robot_body_id=sess.ws.robot_body_id,
            robot_cfg=sess.ws.robot_cfg,       # 월드 base_position 사용
            occlusion_ratio=world["occ_ratio"],
        )
        return physical_oracle.evaluate(
            kin, mutated_local, sess.ws.robot_cfg, self.thresholds,
            test_id=test_id, mutation_params=params,
        )


# ---------------------------------------------------------------------------
# 비교 실험 (random vs active, 동일 세션)
# ---------------------------------------------------------------------------

def run_scene_comparison(
    session: SceneSearchSession,
    thresholds: dict,
    rounds: int,
    tests_per_round: int,
    seed: int = 42,
    log_dir: str = "data/scene3d_search_logs",
) -> dict:
    """같은 HM3D 씬/작업공간에서 random vs active(cold)를 대조한다.

    클러터가 많은 실제 씬은 mutation 공간의 실패 밀도가 높아 발견률만으로는
    포화되기 쉬우므로, "모든 failure type을 커버하기까지 걸린 테스트 수"
    (tests_to_full_coverage)와 발견 심각도(mean robustness of failures)를
    함께 기록한다.
    """
    results = {}
    for mode in ("random", "cold"):
        session.restore()
        cfg = SearchConfig(
            num_rounds=rounds,
            tests_per_round=tests_per_round,
            mode=mode,
            seed=seed,
            log_dir=log_dir,
        )
        search = SceneFailureSearch(session, thresholds, cfg)
        search.run()
        summary = search.summary()

        # 커버리지 속도: n번째 테스트에서 최종 type 집합을 처음 완성한 시점
        all_types = set(summary["unique_failure_types"])
        seen: set[str] = set()
        tests_to_cover = None
        fail_robustness = []
        for i, rec in enumerate(search.dataset):
            if rec.verdict in ("FAIL", "BLOCKED"):
                seen.add(rec.failure_type)
                fail_robustness.append(rec.robustness)
                if tests_to_cover is None and seen == all_types:
                    tests_to_cover = i + 1
        summary["tests_to_full_coverage"] = tests_to_cover
        summary["mean_failure_robustness"] = (
            round(float(np.mean(fail_robustness)), 4) if fail_robustness else None
        )
        results[mode] = summary

    r, a = results["random"], results["cold"]
    print("\n===== HM3D Random vs Active =====")
    for name, s in (("random", r), ("active", a)):
        print(f"  {name}: FAIL+BLOCKED {s['fail'] + s['blocked']}/{s['total_tests']} "
              f"(rate {s['failure_discovery_rate']:.2f}, "
              f"types {s['num_unique_failure_types']}, "
              f"전 유형 커버까지 {s['tests_to_full_coverage']}개 테스트, "
              f"실패 평균 robustness {s['mean_failure_robustness']})")
    return results
