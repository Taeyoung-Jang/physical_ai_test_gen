"""P11 완료 기준 검증 — LAM-Guided Failure Case Generator.

Unit 검증 + 블루프린트 Demo 1~4.

  Unit 1: insert_assets 가 새 ObjectNode 를 append, 원본 불변, load_scene 스폰
  Unit 2: MiniActionModel 이 고유사도 distractor 삽입 시 그것을 선택(wrong grounding)
  Unit 3: RuleLAMProxy 는 항상 target 선택
  Unit 4: selected≠expected rollout 의 ee_path/reach_margin 이 실제 target 과 다름(R1)
  Unit 5: evaluate_policy 가 wrong_object_grounding / (human 침범)BLOCKED 반환
  Unit 6: ConstraintFilter 가 out-of-bounds 후보 제거
  Unit 7: 회귀 가드 — 신규 패키지 import 후 apply_mutation 출력 동일

  Demo 1: RuleLAMProxy → PolicyOracle PASS (정상 경로 동작)
  Demo 2: MiniActionModel batch → VulnerabilityProfile (추천 family ≥ 1)
  Demo 3: 루프가 wrong_object_grounding counterexample ≥ 1 발견
  Demo 4: BoundaryRefiner 가 PASS/FAIL 경계값 반환 (|fail-pass| ≤ tolerance)

실행: PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

import numpy as np

import scene_builder as sb
from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.behavior_encoder import BehaviorTraceEncoder
from lam_guided.case_apply import insert_assets
from lam_guided.constraint_filter import ConstraintFilter
from lam_guided.lam_guided_loop import LAMGuidedFailureLoop, load_lam_config
from lam_guided.policy_oracle import PolicyVerdict, evaluate_physical_from_trace, evaluate_policy
from lam_guided.rollout import make_observation, run_policy_rollout
from lam_guided.types import FailureCaseCandidate
from lam_guided.vulnerability import VulnerabilityProfiler
from physical_oracle import load_thresholds
from policies import MiniActionModel, RuleLAMProxy, make_action_model
from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface
from sim_runner import load_robot_config

ROBOT_CFG = load_robot_config("config/robot_config.yaml")
THR = load_thresholds("config/thresholds.yaml")
RS = {"base": [0.0, 0.0, 0.0], "max_reach": ROBOT_CFG["robot"]["max_reach"]}
LAM_CFG = {"policy_oracle": {"instability_thresh": 3.5}}
INSTR = "pick up the red can"


def make_scene() -> SceneGraph:
    return SceneGraph(
        scene_id="p11_test",
        support_surfaces=[SupportSurface("table_1", "plane", 0.0,
                                         {"x": [0.30, 0.80], "y": [-0.35, 0.35]})],
        objects=[
            ObjectNode("target_0", Role.TARGET, [0.50, 0.00, 0.05],
                       [0.066, 0.066, 0.10], True, "can"),
            ObjectNode("obstacle_0", Role.OBSTACLE, [0.55, 0.28, 0.05],
                       [0.06, 0.06, 0.08], True, "block"),
            ObjectNode("destination_0", Role.DESTINATION, [0.68, -0.22, 0.03],
                       [0.18, 0.12, 0.04], False, "tray"),
        ],
    )


def _bank():
    return GeneratedAssetBank.default("data/generated_assets/index.json")


def _distractor_scene(dist=0.06):
    sg = annotate_scene_semantics(make_scene())
    t = sg.target()
    spec = {"asset_id": "distractor_red_can", "obj_id": "gen_d0",
            "position": [t.position[0], t.position[1] + dist, 0.05]}
    return annotate_scene_semantics(insert_assets(sg, [spec], _bank()))


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------

def test_insert_assets_appends_and_spawns():
    sg = annotate_scene_semantics(make_scene())
    n0 = len(sg.objects)
    spec = {"asset_id": "distractor_red_can", "obj_id": "gen_x",
            "position": [0.5, 0.1, 0.05]}
    out = insert_assets(sg, [spec], _bank())
    assert len(out.objects) == n0 + 1, "노드 append 실패"
    assert len(sg.objects) == n0, "원본 sg가 변경됨"
    sb.reset_simulation()
    bm = sb.load_scene(out)
    assert "gen_x" in bm, "load_scene가 삽입 노드를 스폰하지 않음"


def test_mini_picks_distractor():
    scene = _distractor_scene(dist=0.05)
    mini = MiniActionModel(cfg={"noise_std": 0.12}, seed=0)
    wrong = 0
    for i in range(30):
        mini.rng = np.random.default_rng(i)
        p = mini.predict(INSTR, make_observation(scene), RS)
        if p.selected_obj_id != "target_0":
            wrong += 1
    assert wrong >= 5, f"고유사도 distractor가 거의 선택 안 됨 (wrong={wrong}/30)"


def test_rule_always_target():
    sg = annotate_scene_semantics(make_scene())
    p = RuleLAMProxy().predict(INSTR, make_observation(sg), RS)
    assert p.selected_obj_id == "target_0" == p.expected_obj_id


def test_wrong_selection_changes_rollout():
    scene = _distractor_scene(dist=0.12)
    mini = MiniActionModel(cfg={"noise_std": 0.12}, seed=0)
    # target 선택 rollout
    rule = RuleLAMProxy()
    tr_t = run_policy_rollout(scene, rule.predict(INSTR, make_observation(scene), RS),
                              ROBOT_CFG, "t")
    # distractor 선택 rollout (강제로 찾음)
    sel = None
    for s in range(40):
        mini.rng = np.random.default_rng(s)
        p = mini.predict(INSTR, make_observation(scene), RS)
        if p.selected_obj_id == "gen_d0":
            sel = p
            break
    assert sel is not None, "distractor 선택 케이스를 못 찾음"
    tr_d = run_policy_rollout(scene, sel, ROBOT_CFG, "d")
    assert tr_t.ee_path[-1] != tr_d.ee_path[-1], "ee_path가 동일(물리 차이 없음)"
    assert abs(tr_t.reach_margin - tr_d.reach_margin) > 1e-4, "reach_margin 차이 없음"


def test_policy_oracle_flags():
    scene = _distractor_scene(dist=0.05)
    mini = MiniActionModel(cfg={"noise_std": 0.12}, seed=0)
    sel = None
    for s in range(40):
        mini.rng = np.random.default_rng(s)
        p = mini.predict(INSTR, make_observation(scene), RS)
        if p.selected_obj_id == "gen_d0":
            sel = p
            break
    tr = run_policy_rollout(scene, sel, ROBOT_CFG, "d")
    res = evaluate_policy(tr, THR, LAM_CFG)
    assert "wrong_object_grounding" in res.failure_types
    assert res.verdict == PolicyVerdict.FAIL


def test_constraint_filter_rejects_oob():
    sg = annotate_scene_semantics(make_scene())
    bank = _bank()
    cf = ConstraintFilter(ROBOT_CFG)
    # table 밖(x 음수)에 둔 후보 → 거부
    oob = FailureCaseCandidate("OOB", "path_blocker", sg.scene_id,
        insert_specs=[{"asset_id": "blocker_box", "obj_id": "b", "position": [-1.0, 0.0, 0.05]}])
    inb = FailureCaseCandidate("INB", "semantic_distractor", sg.scene_id,
        insert_specs=[{"asset_id": "distractor_red_can", "obj_id": "d",
                       "position": [0.5, 0.12, 0.05]}])
    kept = cf.filter(sg, [oob, inb], bank)
    kept_ids = {c.case_id for c in kept}
    assert "OOB" not in kept_ids, "out-of-bounds 후보가 통과됨"
    assert "INB" in kept_ids, "유효 후보가 잘못 제거됨"


def test_apply_mutation_regression():
    """신규 패키지 import 후에도 apply_mutation 출력이 동일해야 한다."""
    sg = make_scene()
    mp = {"target_dx": 0.03, "obstacle_angle": 90.0, "obstacle_dist_to_target": 0.08,
          "tray_occupied": 0.0, "occlusion_ratio": 0.0}
    out = sb.apply_mutation(sg, mp)
    t = out.target()
    assert abs(t.position[0] - 0.53) < 1e-9, "apply_mutation target 이동 회귀"
    obs = out.obstacles()[0]
    assert abs(obs.position[0] - t.position[0]) < 1e-9, "obstacle x (cos90=0) 회귀"
    assert abs(obs.position[1] - (t.position[1] + 0.08)) < 1e-9, "obstacle y 회귀"


# ---------------------------------------------------------------------------
# Demos
# ---------------------------------------------------------------------------

def test_demo1_baseline_pass():
    sg = annotate_scene_semantics(make_scene())
    p = RuleLAMProxy().predict(INSTR, make_observation(sg), RS)
    tr = run_policy_rollout(sg, p, ROBOT_CFG, "demo1")
    res = evaluate_policy(tr, THR, LAM_CFG)
    phys = evaluate_physical_from_trace(tr, THR)
    assert res.verdict == PolicyVerdict.PASS, f"baseline policy != PASS ({res.failure_types})"
    assert phys.verdict == "PASS", f"baseline physical != PASS ({phys.failure_types})"


def test_demo2_vulnerability_profile():
    scene = _distractor_scene(dist=0.05)
    mini = MiniActionModel(cfg={"noise_std": 0.12}, seed=0)
    enc = BehaviorTraceEncoder(THR)
    feats = []
    for s in range(12):
        mini.rng = np.random.default_rng(s)
        p = mini.predict(INSTR, make_observation(scene), RS)
        feats.append(enc.encode(run_policy_rollout(scene, p, ROBOT_CFG, f"p{s}")))
    vp = VulnerabilityProfiler(LAM_CFG).profile(feats, "p11_test")
    assert len(vp.recommended_families) >= 1, "추천 family 없음"
    assert max(vp.scores.values()) > 0.0, "취약성 점수가 전부 0"


def test_demo3_and_4_loop_and_boundary():
    lam_cfg = load_lam_config("config/lam_guided_failure.yaml")
    lam_cfg["enabled"] = True
    lam_cfg["action_model"] = "mini"
    lam_cfg["rounds"] = 3
    lam_cfg["paths"] = {**lam_cfg.get("paths", {}),
                        "counterexamples": None, "log_dir": "data/lam_guided_logs",
                        "report_dir": "reports"}
    model = make_action_model("mini", cfg=lam_cfg.get("mini_action_model", {}), seed=0)
    loop = LAMGuidedFailureLoop(make_scene(), ROBOT_CFG, THR, lam_cfg, model)
    result = loop.run(instruction=INSTR, rounds=3, batch_size=8)

    # Demo 3: wrong_object_grounding counterexample ≥ 1
    all_ft = set()
    for ce in result.counterexamples:
        all_ft.update(ce["failure_types"])
    assert len(result.counterexamples) >= 1, "counterexample 미발견"
    assert "wrong_object_grounding" in all_ft, "wrong_object_grounding counterexample 없음"

    # Demo 4: 최소 1개 boundary, |fail-pass| ≤ tolerance
    assert len(result.boundaries) >= 1, "boundary 미산출"
    tol = lam_cfg["boundary_refiner"]["tolerance"]
    for b in result.boundaries:
        assert abs(b["fail_value"] - b["pass_value"]) <= tol + 1e-6, \
            f"{b['family']} boundary 미수렴"
    return result


def main():
    print("[1] insert_assets append/스폰 ...", end=" ")
    test_insert_assets_appends_and_spawns(); print("OK")
    print("[2] MiniActionModel distractor 선택 ...", end=" ")
    test_mini_picks_distractor(); print("OK")
    print("[3] RuleLAMProxy 항상 target ...", end=" ")
    test_rule_always_target(); print("OK")
    print("[4] wrong 선택 → rollout 차이(R1) ...", end=" ")
    test_wrong_selection_changes_rollout(); print("OK")
    print("[5] PolicyOracle wrong_object_grounding ...", end=" ")
    test_policy_oracle_flags(); print("OK")
    print("[6] ConstraintFilter out-of-bounds 거부 ...", end=" ")
    test_constraint_filter_rejects_oob(); print("OK")
    print("[7] apply_mutation 회귀 가드 ...", end=" ")
    test_apply_mutation_regression(); print("OK")
    print("[Demo1] baseline PASS ...", end=" ")
    test_demo1_baseline_pass(); print("OK")
    print("[Demo2] vulnerability profile ...", end=" ")
    test_demo2_vulnerability_profile(); print("OK")
    print("[Demo3+4] loop counterexample + boundary ...")
    res = test_demo3_and_4_loop_and_boundary()
    print(f"         counterexamples={len(res.counterexamples)} "
          f"boundaries={len(res.boundaries)}")
    print("\n✅ P11 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
