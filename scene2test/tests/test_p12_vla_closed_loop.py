"""P12 완료 기준 검증 — Closed-loop VLA 통합 (GPU 불필요, stub 기반).

  1: render_rgb 가 224x224 실제 RGB(>1색) 생성
  2: closed-loop rollout(stub)이 clean 씬에서 target 에 도달
  3: distractor 삽입 시 wrong_object_grounding 재현 (closed-loop + post-hoc 추정)
  4: OpenVLAPolicy 가 GPU 없이 lazy 로 생성됨 (import/construct 시 모델 미로드)
  5: 산출 RolloutTrace 가 기존 PolicyOracle/physical 체크와 호환

실행: PYBULLET_MODE=DIRECT uv run python tests/test_p12_vla_closed_loop.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

import numpy as np
import pybullet as p
import pybullet_data

import scene_builder
import sim_runner
from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.case_apply import insert_assets
from lam_guided.closed_loop import render_rgb, run_closed_loop_rollout
from lam_guided.policy_oracle import evaluate_physical_from_trace, evaluate_policy
from physical_oracle import load_thresholds
from policies_vla import OpenVLAPolicy, make_closed_loop_policy
from scene_graph import SceneGraph
from sim_runner import load_robot_config

ROBOT_CFG = load_robot_config("config/robot_config.yaml")
THR = load_thresholds("config/thresholds.yaml")
LAM_CFG = {"policy_oracle": {"instability_thresh": 3.5}}
INSTR = "pick up the red can"


def _connect():
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid
    sim_runner._ROBOT_BODY_ID = None
    return cid


def _scene(insert=False, bank=None):
    sg = annotate_scene_semantics(SceneGraph.load("data/scene_library/scene_00001.json"))
    if insert:
        t = sg.target()
        spec = {"asset_id": "distractor_red_can", "obj_id": "gen_d0",
                "position": [t.position[0] + 0.05, t.position[1] + 0.03, 0.05]}
        sg = annotate_scene_semantics(insert_assets(sg, [spec], bank))
    return sg


def main():
    cid = _connect()
    bank = GeneratedAssetBank.default("data/generated_assets/index.json")

    print("[1] render_rgb 224x224 실제 RGB ...", end=" ")
    sg = _scene()
    scene_builder.reset_simulation(); scene_builder.load_scene(sg)
    rgb = render_rgb(cid)
    assert rgb.shape == (224, 224, 3)
    assert len(np.unique(rgb.reshape(-1, 3), axis=0)) > 1, "RGB가 단색(렌더 실패)"
    print("OK")

    print("[2] closed-loop stub → clean 씬 target 도달 ...", end=" ")
    pol = make_closed_loop_policy("stub", seed=1)
    tr = run_closed_loop_rollout(_scene(), pol, ROBOT_CFG, INSTR, "clean")
    assert tr.selected_obj_id == tr.expected_obj_id == "target_0", \
        f"clean 씬에서 target 미도달 (selected={tr.selected_obj_id})"
    assert tr.grasp_success
    print("OK")

    print("[3] distractor → wrong_object_grounding 재현 ...", end=" ")
    dsc = _scene(insert=True, bank=bank)
    wrong = 0
    for s in range(12):
        pol = make_closed_loop_policy("stub", seed=s)
        tr = run_closed_loop_rollout(dsc, pol, ROBOT_CFG, INSTR, f"d{s}")
        res = evaluate_policy(tr, THR, LAM_CFG)
        if "wrong_object_grounding" in res.failure_types:
            wrong += 1
    assert wrong >= 3, f"wrong_object_grounding 재현 실패 ({wrong}/12)"
    print(f"OK ({wrong}/12 wrong)")

    print("[4] OpenVLAPolicy GPU 없이 lazy 생성 ...", end=" ")
    vla = make_closed_loop_policy("openvla", cfg={"unnorm_key": "bridge_orig"})
    assert isinstance(vla, OpenVLAPolicy)
    assert vla._model is None and vla._processor is None, "import 시 모델이 로드됨"
    print("OK")

    print("[5] RolloutTrace ↔ Oracle 호환 ...", end=" ")
    tr = run_closed_loop_rollout(dsc, make_closed_loop_policy("stub", seed=0),
                                 ROBOT_CFG, INSTR, "compat")
    pres = evaluate_policy(tr, THR, LAM_CFG)
    phys = evaluate_physical_from_trace(tr, THR)
    assert pres.verdict in ("PASS", "FAIL", "BLOCKED")
    assert phys.verdict in ("PASS", "FAIL")
    print("OK")

    p.disconnect(physicsClientId=cid)
    print("\n✅ P12 완료 기준 전부 통과 (closed-loop VLA 통합, OpenVLA drop-in 준비)")


if __name__ == "__main__":
    main()
