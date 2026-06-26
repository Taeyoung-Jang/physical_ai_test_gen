"""lam_guided_loop.py — LAM-Guided Failure 루프 오케스트레이터 + CLI.

블루프린트 13/20. 독립 오케스트레이터로, 기존 active_failure_search.py 는 손대지 않는다.

라운드마다:
  1) probe rollout 으로 현재 정책 행동 관찰
  2) BehaviorTraceEncoder + VulnerabilityProfiler 로 약점 추정
  3) FailureCaseGenerator 가 추천 family 후보 생성 → ConstraintFilter
  4) surrogate-free acquisition 점수화 → top-K 선택
  5) 선택 후보 실행(apply_case → policy.predict → rollout → policy/physical oracle)
  6) counterexample 은 FailureMemory 에 저장 → 재프로파일
종료 후 BoundaryRefiner 로 최소 perturbation 경계 탐색 + 리포트 저장.

실행:
  PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
      --scene data/scene_library/scene_00001.json \
      --instruction "pick up the red can" --action-model mini --rounds 4 --enabled
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import yaml

from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.behavior_encoder import BehaviorTraceEncoder
from lam_guided.boundary_refiner import BoundaryRefiner
from lam_guided.case_apply import apply_case
from lam_guided.case_generator import FailureCaseGenerator
from lam_guided.constraint_filter import ConstraintFilter
from lam_guided.failure_memory import FailureMemory
from lam_guided.policy_oracle import PolicyVerdict, evaluate_physical_from_trace, evaluate_policy
from lam_guided.rollout import make_observation, run_policy_rollout
from lam_guided.types import FailureCaseCandidate, VulnerabilityProfile
from lam_guided.vulnerability import VulnerabilityProfiler
from physical_oracle import load_thresholds
from policies import make_action_model
from scene_graph import SceneGraph
from sim_runner import load_robot_config


def load_lam_config(path: str = "config/lam_guided_failure.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["lam_guided_failure"]


@dataclass
class LoopResult:
    scene_id: str
    instruction: str
    action_model: str
    rounds: int
    profile: Optional[dict] = None
    counterexamples: list[dict] = field(default_factory=list)
    boundaries: list[dict] = field(default_factory=list)
    round_summaries: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


class LAMGuidedFailureLoop:
    def __init__(self, base_sg: SceneGraph, robot_cfg: dict, thresholds: dict,
                 lam_cfg: dict, action_model=None):
        self.base_sg = annotate_scene_semantics(base_sg)
        self.robot_cfg = robot_cfg
        self.thr = thresholds
        self.cfg = lam_cfg
        seed = lam_cfg.get("seed", 0)

        self.bank = GeneratedAssetBank.default(
            lam_cfg.get("paths", {}).get("asset_index", "data/generated_assets/index.json"))
        self.policy = action_model or make_action_model(
            lam_cfg.get("action_model", "mini"),
            cfg=lam_cfg.get("mini_action_model", {}), seed=seed)
        self.encoder = BehaviorTraceEncoder(thresholds)
        self.profiler = VulnerabilityProfiler(lam_cfg)
        self.generator = FailureCaseGenerator(self.bank, lam_cfg, robot_cfg, seed=seed)
        self.cfilter = ConstraintFilter(robot_cfg)
        self.memory = FailureMemory(lam_cfg.get("paths", {}).get("counterexamples"))
        self.instruction = lam_cfg.get("instruction_default", "pick up the red can")
        self.rs = {"base": list(robot_cfg["robot"]["base_position"]),
                   "max_reach": robot_cfg["robot"]["max_reach"]}
        self.aw = lam_cfg.get("acquisition_weights", {})
        self._rng = np.random.default_rng(seed)

    # --------------------------------------------------------------- helpers
    def _run_case(self, case: FailureCaseCandidate):
        scene = annotate_scene_semantics(apply_case(self.base_sg, case, self.bank))
        plan = self.policy.predict(case.instruction or self.instruction,
                                   make_observation(scene), self.rs)
        trace = run_policy_rollout(scene, plan, self.robot_cfg, case.case_id)
        result = evaluate_policy(trace, self.thr, self.cfg)
        phys = evaluate_physical_from_trace(trace, self.thr)
        feats = self.encoder.encode(trace)
        return scene, plan, trace, result, phys, feats

    def _stratified_topk(self, cands: list[FailureCaseCandidate], k: int,
                         profile: VulnerabilityProfile) -> list[FailureCaseCandidate]:
        """recommended family 들에 슬롯을 비례 배분해 다양성을 보장한다.

        한 family(예: human_safety)가 batch 를 독점하지 않게 하여 path_blocker /
        occluder 등도 실행·기록되도록 한다.
        """
        by_fam: dict[str, list[FailureCaseCandidate]] = {}
        for c in cands:
            by_fam.setdefault(c.family, []).append(c)
        for fam in by_fam:
            by_fam[fam].sort(key=lambda c: c.acquisition_score, reverse=True)

        fams = [f for f in (profile.recommended_families or list(by_fam))
                if f in by_fam]
        for f in by_fam:                       # 추천에 없는 family도 뒤에 포함
            if f not in fams:
                fams.append(f)
        if not fams:
            return sorted(cands, key=lambda c: c.acquisition_score, reverse=True)[:k]

        chosen: list[FailureCaseCandidate] = []
        idx = {f: 0 for f in fams}
        # round-robin: 추천 순서대로 한 개씩 채운다
        while len(chosen) < k:
            progressed = False
            for f in fams:
                if len(chosen) >= k:
                    break
                if idx[f] < len(by_fam[f]):
                    chosen.append(by_fam[f][idx[f]])
                    idx[f] += 1
                    progressed = True
            if not progressed:
                break
        return chosen

    @staticmethod
    def _combined_verdict(policy_v: str, phys_v: str) -> str:
        if policy_v == PolicyVerdict.BLOCKED:
            return PolicyVerdict.BLOCKED
        if policy_v == PolicyVerdict.FAIL or phys_v == "FAIL":
            return PolicyVerdict.FAIL
        return PolicyVerdict.PASS

    def _score_candidate(self, case: FailureCaseCandidate, feat) -> float:
        w = self.aw
        return (w.get("family_prior", 0.40) * case.family_prior
                + w.get("novelty", 0.25) * self.memory.novelty(feat)
                + w.get("coverage", 0.20) * self.memory.coverage_bonus(case.expected_failure)
                - w.get("redundancy", 0.15) * self.memory.redundancy(feat))

    def _probe(self, n: int) -> VulnerabilityProfile:
        """현재 정책 행동을 관찰: distractor 를 다양하게 삽입한 probe rollout."""
        probe_cases = self.generator.generate(self.base_sg, None, n)
        probe_cases = self.cfilter.filter(self.base_sg, probe_cases, self.bank)[:n]
        feats = []
        for c in probe_cases:
            _, _, _, _, _, f = self._run_case(c)
            feats.append(f)
        return self.profiler.profile(feats, self.base_sg.scene_id)

    # --------------------------------------------------------------- run
    def run(self, instruction: Optional[str] = None,
            rounds: Optional[int] = None,
            batch_size: Optional[int] = None) -> LoopResult:
        instruction = instruction or self.instruction
        self.instruction = instruction
        rounds = rounds or self.cfg.get("rounds", 4)
        batch_size = batch_size or self.cfg.get("top_k_per_round", 8)
        n_cand = self.cfg.get("candidates_per_round", 60)
        n_probe = self.cfg.get("probe_per_round", 10)

        print("\n=== LAM-Guided Failure Loop ===")
        print(f"  scene={self.base_sg.scene_id}  policy={getattr(self.policy,'name','?')}")
        print(f"  instruction=\"{instruction}\"  rounds={rounds}  batch={batch_size}\n")

        profile = None
        summaries = []
        for r in range(rounds):
            t0 = time.perf_counter()
            # 1-2. 행동 관찰 → 취약성
            profile = self._probe(n_probe)

            # 3. guided 후보 생성 + 필터
            cands = self.generator.generate(self.base_sg, profile, n_cand)
            cands = self.cfilter.filter(self.base_sg, cands, self.bank)
            if not cands:
                print(f"  [R{r}] 유효 후보 없음"); continue

            # 4. surrogate-free 점수화 + family-stratified 선택
            for c in cands:
                c.acquisition_score = (
                    self.aw.get("family_prior", 0.40) * c.family_prior
                    + self.aw.get("coverage", 0.20)
                    * self.memory.coverage_bonus(c.expected_failure))
            chosen = self._stratified_topk(cands, batch_size, profile)

            # 5. 실행 + oracle (policy + physical)
            n_fail = 0; types = set()
            for c in chosen:
                scene, plan, trace, result, phys, feats = self._run_case(c)
                combined = self._combined_verdict(result.verdict, phys.verdict)
                if combined in (PolicyVerdict.FAIL, PolicyVerdict.BLOCKED):
                    n_fail += 1
                    types.update(result.failure_types)
                    types.update(phys.failure_types)
                    self.memory.add(c, result, trace, feats,
                                    physical_failures=phys.failure_types,
                                    combined_verdict=combined)

            dt = time.perf_counter() - t0
            print(f"  [R{r}] 후보={len(cands)} 선택={len(chosen)} "
                  f"counterexample={n_fail} 누적CE={len(self.memory)} "
                  f"families={profile.recommended_families} ({dt:.1f}s)")
            summaries.append({
                "round": r, "candidates": len(cands), "chosen": len(chosen),
                "counterexamples": n_fail, "cumulative": len(self.memory),
                "recommended_families": profile.recommended_families,
                "failure_types": sorted(types),
            })

        # 6. boundary refine
        boundaries = []
        refiner = BoundaryRefiner(self.bank, self.policy, self.robot_cfg, self.thr, self.cfg)
        for fam in self.cfg.get("boundary_refiner", {}).get("families", []):
            ce = self.memory.top_for_family(fam)
            if ce is None:
                continue
            br = refiner.refine(self.base_sg, ce)
            if br:
                boundaries.append(br.to_dict())
                print(f"  [boundary] {fam}: {br.param_name} 경계≈{br.boundary:.3f}m "
                      f"(fail≤{br.fail_value:.3f} / pass≥{br.pass_value:.3f})")

        result = LoopResult(
            scene_id=self.base_sg.scene_id, instruction=instruction,
            action_model=getattr(self.policy, "name", "?"), rounds=rounds,
            profile=profile.to_dict() if profile else None,
            counterexamples=self.memory.records(),
            boundaries=boundaries, round_summaries=summaries,
        )
        self._save(result)
        self._report(result)
        return result

    # --------------------------------------------------------------- io
    def _save(self, result: LoopResult) -> None:
        log_dir = self.cfg.get("paths", {}).get("log_dir", "data/lam_guided_logs")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"lam_{result.scene_id}_{int(time.time())}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n  로그 저장: {path}")

    def _report(self, result: LoopResult) -> None:
        try:
            import reporter
        except Exception:
            return
        rep_dir = self.cfg.get("paths", {}).get("report_dir", "reports")
        if result.profile:
            reporter.generate_vulnerability_summary(result.profile, rep_dir)
        reporter.generate_counterexample_table(result.counterexamples, rep_dir)
        reporter.generate_boundary_report(result.boundaries, rep_dir)
        print(f"  리포트 저장: {rep_dir}/ (vulnerability_summary.md, "
              f"counterexample_table.csv, boundary_report.md)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="LAM-Guided Failure Case Generator")
    ap.add_argument("--scene", default="data/scene_library/scene_00001.json")
    ap.add_argument("--instruction", default=None)
    ap.add_argument("--action-model", choices=["mini", "rule"], default=None)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--config", default="config/lam_guided_failure.yaml")
    ap.add_argument("--enabled", action="store_true",
                    help="config의 enabled flag를 덮어써 강제 실행")
    args = ap.parse_args()

    lam_cfg = load_lam_config(args.config)
    if args.action_model:
        lam_cfg["action_model"] = args.action_model
    if not (lam_cfg.get("enabled", False) or args.enabled):
        print("lam_guided_failure.enabled=false 이며 --enabled 도 없음 → 실행하지 않음.")
        print("  활성화: --enabled 또는 config의 enabled: true")
        return

    robot_cfg = load_robot_config("config/robot_config.yaml")
    thr = load_thresholds("config/thresholds.yaml")
    base_sg = SceneGraph.load(args.scene)

    action_model = make_action_model(
        lam_cfg.get("action_model", "mini"),
        cfg=lam_cfg.get("mini_action_model", {}), seed=lam_cfg.get("seed", 0))

    loop = LAMGuidedFailureLoop(base_sg, robot_cfg, thr, lam_cfg, action_model)
    loop.run(instruction=args.instruction, rounds=args.rounds, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
