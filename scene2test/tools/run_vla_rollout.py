"""tools/run_vla_rollout.py — closed-loop VLA 정책 rollout 데모 CLI.

VLA(또는 stub)를 closed-loop 으로 구동해 한 케이스를 실행하고 Policy/Physical Oracle
판정을 출력한다. --gif 면 VLA가 보는 RGB 관측 시퀀스를 GIF 로 저장한다.

  # stub(GPU 불필요) — 파이프라인 데모
  PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
      --scene data/scene_library/scene_00001.json --policy stub \
      --insert distractor_red_can --gif

  # 실제 OpenVLA (GPU 환경에서)
  PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
      --scene data/scene_library/scene_00001.json --policy openvla \
      --instruction "pick up the red can"
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pybullet as p

import scene_builder
import sim_runner
from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.case_apply import insert_assets
from lam_guided.closed_loop import run_closed_loop_rollout
from lam_guided.policy_oracle import evaluate_physical_from_trace, evaluate_policy
from physical_oracle import load_thresholds
from policies_vla import make_closed_loop_policy
from scene_graph import SceneGraph
from sim_runner import load_robot_config


def parse_args():
    ap = argparse.ArgumentParser(description="closed-loop VLA rollout 데모")
    ap.add_argument("--scene", default="data/scene_library/scene_00001.json")
    ap.add_argument("--policy", choices=["stub", "openvla"], default="stub")
    ap.add_argument("--instruction", default="pick up the red can")
    ap.add_argument("--insert", help="삽입할 asset_id (예: distractor_red_can)")
    ap.add_argument("--insert-dx", type=float, default=0.05)
    ap.add_argument("--insert-dy", type=float, default=0.03)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gif", action="store_true", help="VLA 관측 RGB 시퀀스를 GIF 저장")
    ap.add_argument("--output", default="data/lam_anim/vla_rollout.gif")
    # OpenVLA 옵션
    ap.add_argument("--unnorm-key", default="bridge_orig")
    ap.add_argument("--device", default="auto",
                    help="auto(권장) | mps(Apple Silicon) | cuda:0 | cpu")
    ap.add_argument("--pos-scale", type=float, default=1.0)
    return ap.parse_args()


def main():
    args = parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    robot_cfg = load_robot_config("config/robot_config.yaml")
    thr = load_thresholds("config/thresholds.yaml")
    bank = GeneratedAssetBank.default("data/generated_assets/index.json")

    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid
    sim_runner._ROBOT_BODY_ID = None

    sg = annotate_scene_semantics(SceneGraph.load(args.scene))
    if args.insert:
        t = sg.target()
        spec = {"asset_id": args.insert, "obj_id": "gen_insert",
                "position": [t.position[0] + args.insert_dx,
                             t.position[1] + args.insert_dy, 0.05]}
        sg = annotate_scene_semantics(insert_assets(sg, [spec], bank))

    cfg = {"unnorm_key": args.unnorm_key, "device": args.device,
           "pos_scale": args.pos_scale}
    policy = make_closed_loop_policy(args.policy, cfg=cfg, seed=args.seed)

    print("\n=== Closed-loop VLA Rollout ===")
    print(f"  policy={args.policy}  scene={sg.scene_id}  insert={args.insert}")
    print(f"  instruction=\"{args.instruction}\"\n")

    result = run_closed_loop_rollout(
        sg, policy, robot_cfg, args.instruction, "vla_demo",
        max_steps=args.max_steps, collect_frames=args.gif)
    trace, frames = result if args.gif else (result, None)

    pres = evaluate_policy(trace, thr, {"policy_oracle": {"instability_thresh": 3.5}})
    phys = evaluate_physical_from_trace(trace, thr)

    print(f"  steps={trace.kinematic['steps']}  grasped={trace.grasp_success}")
    print(f"  selected={trace.selected_obj_id}  expected={trace.expected_obj_id}")
    print(f"  POLICY  : {pres.verdict}  {pres.failure_types}")
    print(f"  PHYSICAL: {phys.verdict}  {phys.failure_types}")
    if pres.reason:
        print(f"  reason  : {pres.reason}")

    if args.gif and frames:
        import imageio
        uniq = len({f.tobytes() for f in frames})
        if uniq > 1:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            imageio.mimsave(args.output, frames, fps=8, loop=0)
            print(f"\n  관측 GIF 저장: {args.output} ({len(frames)}프레임, {uniq}개 고유)")
        else:
            print("\n  ⚠️ 관측 프레임이 모두 동일 — 저장 안 함")

    p.disconnect(physicsClientId=cid)
    print("\n✓ 완료")


if __name__ == "__main__":
    main()
