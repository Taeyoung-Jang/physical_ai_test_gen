"""policies.py — 교체 가능한 ActionModel (LAM/VLA 대리자).

블루프린트 6.1/7.1: 실제 LAM/VLA가 있든 없든 시스템은 동일한 ActionModel 인터페이스로
action plan을 받는다. MVP는 두 구현을 제공한다.

  RuleLAMProxy   : 항상 정답 target 선택 (baseline, Demo 1)
  MiniActionModel: 색/형상/instruction 키워드 매칭 + 노이즈 기반 휴리스틱.
                   유사도 높은 distractor가 들어오면 wrong object grounding이 발생.

정책은 PyBullet 렌더 색이 아니라 ObjectNode.extra 의 semantic_tags /
visual_similarity_to_target 를 읽는다(스키마 불변).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol

import numpy as np

from scene_graph import ObjectNode, Role, SceneGraph

# ---------------------------------------------------------------------------
# Action plan 자료구조
# ---------------------------------------------------------------------------

@dataclass
class ActionSubgoal:
    kind: str                            # "reach" | "grasp" | "lift" | "place" | "stop"
    target_obj_id: str
    position: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionPlan:
    instruction: str
    selected_obj_id: str                 # 정책이 조작하기로 결정한 객체
    expected_obj_id: str                 # ground-truth target id
    subgoals: list[ActionSubgoal] = field(default_factory=list)
    confidence: float = 1.0
    object_scores: dict[str, float] = field(default_factory=dict)
    stopped_for_safety: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["subgoals"] = [s.to_dict() for s in self.subgoals]
        return d


# ---------------------------------------------------------------------------
# 인터페이스
# ---------------------------------------------------------------------------

class ActionModel(Protocol):
    def predict(
        self,
        instruction: str,
        observation: SceneGraph,
        robot_state: dict[str, Any],
    ) -> ActionPlan: ...


def _pick_place_subgoals(target: ObjectNode,
                         destination: Optional[ObjectNode]) -> list[ActionSubgoal]:
    subs = [
        ActionSubgoal("reach", target.id, list(target.position)),
        ActionSubgoal("grasp", target.id, list(target.position)),
    ]
    if destination is not None:
        subs.append(ActionSubgoal("place", destination.id, list(destination.position)))
        subs.append(ActionSubgoal("release", destination.id, list(destination.position)))
    return subs


# ---------------------------------------------------------------------------
# RuleLAMProxy — 항상 정답 (baseline)
# ---------------------------------------------------------------------------

class RuleLAMProxy:
    """기존 scripted pick-and-place를 LAM 인터페이스로 감싼 baseline.

    instruction과 무관하게 항상 sg.target() 을 선택한다 → wrong grounding 없음.
    """

    name = "rule_lam_proxy"

    def predict(self, instruction, observation, robot_state) -> ActionPlan:
        target = observation.target()
        dest = observation.destination()
        if target is None:
            return ActionPlan(instruction, selected_obj_id="", expected_obj_id="",
                              confidence=0.0)
        return ActionPlan(
            instruction=instruction,
            selected_obj_id=target.id,
            expected_obj_id=target.id,
            subgoals=_pick_place_subgoals(target, dest),
            confidence=1.0,
            object_scores={target.id: 1.0},
        )


# ---------------------------------------------------------------------------
# MiniActionModel — 휴리스틱 confusion model (딥러닝 아님)
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {"keyword": 0.5, "similarity": 0.4, "occlusion": 0.3,
                    "distance": 0.15, "proximity": 0.35}
# proximity: 기대 target 근처 객체에 주는 선택 보너스. 가까운 distractor 일수록
# 더 헷갈리게 만들어 distance_to_target 가 의미 있는 경계 parameter 가 되게 한다.
_PROXIMITY_SCALE = 0.15  # m, 이 거리 안에서 보너스가 선형 감소


def _keywords(instruction: str) -> list[str]:
    return [w for w in instruction.lower().replace(".", " ").split() if len(w) > 2]


def _tag_match(keywords: list[str], tags: list[str]) -> float:
    """instruction 키워드와 객체 semantic tag 의 교집합 비율 [0,1]."""
    if not keywords:
        return 0.0
    tagset = {t.lower() for t in tags}
    hits = sum(1 for k in keywords if k in tagset)
    return hits / len(keywords)


def _occlusion_at(sg: SceneGraph, obj: ObjectNode) -> float:
    """객체가 unknown_region(가림)에 얼마나 덮여 있는지 [0,1]."""
    if not sg.unknown_regions:
        return 0.0
    op = np.array(obj.position[:2])
    worst = 0.0
    for region in sg.unknown_regions:
        c = np.array(region.center[:2])
        d = float(np.linalg.norm(op - c))
        if d <= region.radius:
            worst = max(worst, region.occlusion_ratio)
    return worst


class MiniActionModel:
    """객체별 점수 = 키워드매칭 + 시각유사도 − 가림 − 거리 + 노이즈 → argmax.

    유사도 높은 distractor가 target을 이기면 wrong object grounding이 발생한다.
    """

    name = "mini_action_model"

    def __init__(self, cfg: Optional[dict] = None, seed: int = 0):
        cfg = cfg or {}
        self.noise_std = cfg.get("noise_std", 0.12)
        self.safety_aware = cfg.get("safety_aware", False)
        self.w = {**_DEFAULT_WEIGHTS, **cfg.get("weights", {})}
        self.rng = np.random.default_rng(seed)

    # -- 선택 점수 --
    def _object_score(self, sg: SceneGraph, obj: ObjectNode,
                      keywords: list[str], robot_base: np.ndarray,
                      max_reach: float, target_pos: Optional[np.ndarray],
                      expected_id: str) -> float:
        tags = obj.extra.get("semantic_tags", [])
        sim = float(obj.extra.get("visual_similarity_to_target", 0.0))
        kw = _tag_match(keywords, tags)
        occ = _occlusion_at(sg, obj)
        dist = float(np.linalg.norm(np.array(obj.position) - robot_base)) / max(max_reach, 1e-6)
        # decoy 가 기대 target 근처일수록 주의를 빼앗음(salience). target 자신은 제외.
        prox = 0.0
        if target_pos is not None and obj.id != expected_id:
            dt = float(np.linalg.norm(np.array(obj.position[:2]) - target_pos[:2]))
            prox = max(0.0, 1.0 - dt / _PROXIMITY_SCALE)
        score = (self.w["keyword"] * kw
                 + self.w["similarity"] * sim
                 + self.w.get("proximity", 0.0) * prox
                 - self.w["occlusion"] * occ
                 - self.w["distance"] * dist)
        score += float(self.rng.normal(0.0, self.noise_std))
        return score

    def predict(self, instruction, observation, robot_state) -> ActionPlan:
        expected = observation.target()
        dest = observation.destination()
        robot_base = np.array(robot_state.get("base", [0.0, 0.0, 0.0]))
        max_reach = robot_state.get("max_reach", 0.855)
        keywords = _keywords(instruction)

        # 선택 후보: target / obstacle / distractor (destination·human_zone 제외)
        candidates = [o for o in observation.objects
                      if o.role in (Role.TARGET, Role.OBSTACLE, Role.DISTRACTOR)]
        if not candidates:
            return ActionPlan(instruction, "", expected.id if expected else "",
                              confidence=0.0)

        target_pos = np.array(expected.position) if expected is not None else None
        expected_id = expected.id if expected is not None else ""
        scores = {o.id: self._object_score(observation, o, keywords, robot_base,
                                           max_reach, target_pos, expected_id)
                  for o in candidates}
        selected_id = max(scores, key=scores.get)
        selected = observation.get_object(selected_id)

        # softmax 신뢰도
        vals = np.array(list(scores.values()))
        ex = np.exp(vals - vals.max())
        conf = float(ex[list(scores).index(selected_id)] / ex.sum())

        # 안전 인지: 경로가 human_zone 근처면 멈춤 (safety_aware일 때만)
        stopped = False
        if self.safety_aware and _path_near_human_zone(observation, selected, robot_base):
            stopped = True

        target_for_plan = selected if selected is not None else expected
        return ActionPlan(
            instruction=instruction,
            selected_obj_id=selected_id,
            expected_obj_id=expected.id if expected else "",
            subgoals=_pick_place_subgoals(target_for_plan, dest),
            confidence=conf,
            object_scores=scores,
            stopped_for_safety=stopped,
        )


def _path_near_human_zone(sg: SceneGraph, target: ObjectNode,
                          robot_base: np.ndarray, safety_dist: float = 0.30) -> bool:
    """robot_base→target 직선과 human_zone 중심의 2D 최단거리가 safety_dist 미만인지."""
    if target is None:
        return False
    a = robot_base[:2]
    b = np.array(target.position[:2])
    ab = b - a
    ab_len2 = float(ab @ ab)
    for hz in sg.human_zones():
        p = np.array(hz.position[:2])
        if ab_len2 < 1e-9:
            d = float(np.linalg.norm(p - a))
        else:
            t = max(0.0, min(1.0, float((p - a) @ ab) / ab_len2))
            proj = a + t * ab
            d = float(np.linalg.norm(p - proj))
        if d < safety_dist:
            return True
    return False


# ---------------------------------------------------------------------------
# 팩토리
# ---------------------------------------------------------------------------

def make_action_model(kind: str, cfg: Optional[dict] = None, seed: int = 0) -> ActionModel:
    if kind in ("rule", "rule_lam_proxy"):
        return RuleLAMProxy()
    if kind in ("mini", "mini_action_model"):
        return MiniActionModel(cfg=cfg, seed=seed)
    raise ValueError(f"unknown action_model: {kind}")
