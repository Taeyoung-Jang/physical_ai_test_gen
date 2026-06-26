"""case_generator.py — LAM-Guided Failure Case Generator (4 family).

블루프린트 8. vulnerability profile + asset bank 를 이용해, 정책이 취약한
failure family 의 후보 테스트(FailureCaseCandidate)를 생성한다.

Family:
  semantic_distractor     : target 근처에 고유사도 distractor 삽입 (wrong grounding)
  occluder                : camera-target 사이 tall obstacle + occlusion_ratio (perception)
  path_blocker            : robot_base→target 경로 위 obstacle (clearance/collision)
  human_safety_intrusion  : 경로 근처 human_proxy 삽입 (safety)
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.types import FailureCaseCandidate, VulnerabilityProfile
from scene_graph import SceneGraph

_FAMILIES = ["semantic_distractor", "occluder", "path_blocker", "human_safety_intrusion"]


class FailureCaseGenerator:
    def __init__(self, asset_bank: GeneratedAssetBank, lam_cfg: dict,
                 robot_cfg: dict, seed: int = 0):
        self.bank = asset_bank
        self.robot_base = np.array(robot_cfg["robot"]["base_position"])
        gcfg = lam_cfg.get("generator", {})
        self.selection_radius = gcfg.get("selection_radius", 0.12)
        self.min_separation = gcfg.get("min_separation", 0.04)
        self.occlusion_default = gcfg.get("occlusion_default", 0.55)
        self.enabled_families = lam_cfg.get("enabled_families", _FAMILIES)
        self.instruction = lam_cfg.get("instruction_default", "pick up the red can")
        self.rng = np.random.default_rng(seed)
        self._counter = 0

    def _cid(self, family: str) -> str:
        self._counter += 1
        return f"LAMFC_{family[:4]}_{self._counter:04d}"

    # ----------------------------------------------------------------- family
    def _semantic_distractor(self, sg: SceneGraph, n: int) -> list[FailureCaseCandidate]:
        target = sg.target()
        if target is None:
            return []
        assets = self.bank.query(family="semantic_distractor", min_similarity=0.5)
        if not assets:
            return []
        out = []
        for _ in range(n):
            asset = assets[int(self.rng.integers(len(assets)))]
            dist = float(self.rng.uniform(self.min_separation, self.selection_radius))
            ang = float(self.rng.uniform(0, 2 * math.pi))
            pos = [target.position[0] + dist * math.cos(ang),
                   target.position[1] + dist * math.sin(ang),
                   asset.size[2] / 2]
            cid = self._cid("semantic_distractor")
            out.append(FailureCaseCandidate(
                case_id=cid, family="semantic_distractor", base_scene_id=sg.scene_id,
                instruction=self.instruction,
                insert_specs=[{"asset_id": asset.asset_id, "obj_id": f"{cid}_obj",
                               "position": pos}],
                expected_failure="wrong_object_grounding",
                primary_param={"name": "distance_to_target", "value": dist,
                               "asset_id": asset.asset_id, "angle": ang},
            ))
        return out

    def _occluder(self, sg: SceneGraph, n: int) -> list[FailureCaseCandidate]:
        target = sg.target()
        if target is None:
            return []
        assets = self.bank.query(family="occluder")
        if not assets:
            return []
        # camera 는 robot_base 쪽(앞)에서 본다고 가정: base→target 방향의 target 앞쪽
        tp = np.array(target.position)
        view = tp[:2] - self.robot_base[:2]
        view = view / (np.linalg.norm(view) + 1e-9)
        out = []
        for _ in range(n):
            asset = assets[int(self.rng.integers(len(assets)))]
            standoff = float(self.rng.uniform(0.05, 0.10))
            occ = float(np.clip(self.occlusion_default + self.rng.uniform(-0.1, 0.1), 0.3, 0.7))
            pos = [tp[0] - view[0] * standoff, tp[1] - view[1] * standoff, asset.size[2] / 2]
            cid = self._cid("occluder")
            out.append(FailureCaseCandidate(
                case_id=cid, family="occluder", base_scene_id=sg.scene_id,
                instruction=self.instruction,
                insert_specs=[{"asset_id": asset.asset_id, "obj_id": f"{cid}_obj",
                               "position": pos}],
                occlusion_ratio=occ, expected_failure="occlusion_failure",
                primary_param={"name": "occlusion_ratio", "value": occ,
                               "asset_id": asset.asset_id, "standoff": standoff},
            ))
        return out

    def _path_blocker(self, sg: SceneGraph, n: int) -> list[FailureCaseCandidate]:
        """target 의 grasp 접근 영역(근처)에 obstacle 을 배치해 clearance/collision 유도.

        로봇은 target 위에서 수직 하강하므로, target 근처(거리 d)에 둔 obstacle 이
        target_clearance 를 잠식한다. d 가 작을수록 FAIL(insufficient_clearance/collision).
        boundary parameter = offset_from_path (= target 으로부터의 거리).
        """
        target = sg.target()
        if target is None:
            return []
        assets = self.bank.query(family="path_blocker")
        if not assets:
            return []
        # 로봇 쪽(앞)을 향하게 두어 항상 table 안에 들어오게 한다
        a = self.robot_base[:2]
        b = np.array(target.position[:2])
        toward_robot = a - b
        toward_robot = toward_robot / (np.linalg.norm(toward_robot) + 1e-9)
        out = []
        for _ in range(n):
            asset = assets[int(self.rng.integers(len(assets)))]
            d = float(self.rng.uniform(0.02, 0.10))     # target 으로부터 거리
            pt = b + d * toward_robot
            pos = [float(pt[0]), float(pt[1]), asset.size[2] / 2]
            cid = self._cid("path_blocker")
            out.append(FailureCaseCandidate(
                case_id=cid, family="path_blocker", base_scene_id=sg.scene_id,
                instruction=self.instruction,
                insert_specs=[{"asset_id": asset.asset_id, "obj_id": f"{cid}_obj",
                               "position": pos}],
                expected_failure="collision_or_clearance_failure",
                primary_param={"name": "offset_from_path", "value": d,
                               "asset_id": asset.asset_id},
            ))
        return out

    def _human_safety(self, sg: SceneGraph, n: int) -> list[FailureCaseCandidate]:
        target = sg.target()
        if target is None:
            return []
        assets = self.bank.query(family="human_safety_intrusion")
        if not assets:
            return []
        a = self.robot_base[:2]
        b = np.array(target.position[:2])
        ab = b - a
        normal = np.array([-ab[1], ab[0]])
        normal = normal / (np.linalg.norm(normal) + 1e-9)
        out = []
        for _ in range(n):
            asset = assets[0]
            t = float(self.rng.uniform(0.4, 0.7))
            dist = float(self.rng.uniform(0.08, 0.20))   # 경로로부터 거리 (safety_distance 미만 유도)
            side = 1.0 if self.rng.random() < 0.5 else -1.0
            pt = a + t * ab + side * dist * normal
            pos = [float(pt[0]), float(pt[1]), 0.0]
            cid = self._cid("human_safety_intrusion")
            out.append(FailureCaseCandidate(
                case_id=cid, family="human_safety_intrusion", base_scene_id=sg.scene_id,
                instruction=self.instruction,
                insert_specs=[{"asset_id": asset.asset_id, "obj_id": f"{cid}_obj",
                               "position": pos}],
                expected_failure="safety_noncompliance",
                primary_param={"name": "distance_to_path", "value": dist,
                               "asset_id": asset.asset_id, "t": t, "side": side},
            ))
        return out

    # ----------------------------------------------------------------- public
    def generate(self, sg: SceneGraph, profile: Optional[VulnerabilityProfile],
                 n_candidates: int) -> list[FailureCaseCandidate]:
        """vulnerability profile 의 family_weights 에 비례해 후보를 배분 생성한다."""
        families = [f for f in self.enabled_families]
        if profile and profile.family_weights:
            weights = np.array([max(profile.family_weights.get(f, 0.0), 1e-3)
                                for f in families])
        else:
            weights = np.ones(len(families))
        weights = weights / weights.sum()
        counts = np.maximum(1, np.round(weights * n_candidates).astype(int))

        gen_map = {
            "semantic_distractor": self._semantic_distractor,
            "occluder": self._occluder,
            "path_blocker": self._path_blocker,
            "human_safety_intrusion": self._human_safety,
        }
        out: list[FailureCaseCandidate] = []
        for fam, k in zip(families, counts):
            if fam in gen_map:
                cands = gen_map[fam](sg, int(k))
                prior = profile.family_weights.get(fam, 0.0) if profile else 0.0
                for c in cands:
                    c.family_prior = prior
                out.extend(cands)
        return out
