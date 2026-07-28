"""run_stance_test.py — 다리로 서는 로봇(quadruped/humanoid/임의 URDF)의 stance
(정적 자립) 실패 탐색을 실제 3D scene 바닥 위에서 실행한다.

팔 파이프라인(workspace_setup.py/failure_search.py)과 달리 지지면(support surface)이나
IK가 필요 없다 — 다리 로봇은 그냥 바닥(mesh_loader.find_free_floor_spots가 찾은 지점)
위에 서기만 하면 된다. 각 지점마다 실제 물리 시뮬레이션(중력 + position-hold 모터)을
--steps 만큼 돌려 넘어지는지/서 있는지를 scene3d.legged.run_stance_trial로 판정한다.

내장 로봇(laikago/humanoid)은 src/scene3d/legged.py에서 실측으로 검증된 home pose를
쓴다. --urdf로 임의 URDF를 지정하면 scene3d.legged.spec_from_urdf()가 그 URDF의
"모든 관절 0 위치"를 home pose로 자동 구성해 같은 경로로 테스트한다 — 전용 SPEC이
없는 로봇도 동일하게 "일단 서보기"를 시도할 수 있다(실패해도 정당한 결과).

사용:
  # 내장 로봇으로 HM3D 씬에서 스탠스 테스트
  PYBULLET_MODE=DIRECT uv run python tools/run_stance_test.py \
      --source 00802 --robot laikago --trials 5

  PYBULLET_MODE=DIRECT uv run python tools/run_stance_test.py \
      --source 00802 --robot humanoid --trials 5 --steps 240

  # 임의 URDF로 "일반 로봇" 테스트 (pybullet_data 상대경로 또는 절대경로)
  PYBULLET_MODE=DIRECT uv run python tools/run_stance_test.py \
      --source 00802 --urdf quadruped/quadruped.urdf --trials 3

출력: 지점별 PASS/FAIL + 요약(성공률). --log 지정 시 JSON으로도 저장.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p
import pybullet_data


def parse_args():
    parser = argparse.ArgumentParser(description="다리 로봇 stance 실패 탐색")
    parser.add_argument(
        "--source", default="00800",
        help="HM3D scene id | mesh 파일 경로(.glb/.obj/.ply)",
    )
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--robot", default="laikago", choices=["laikago", "humanoid"])
    parser.add_argument(
        "--urdf", default=None,
        help="지정 시 --robot 대신 이 URDF로 spec_from_urdf() 자동 스펙 생성",
    )
    parser.add_argument(
        "--fixed-base", action="store_true",
        help="로봇 base를 world에 고정(관절만 움직임 확인용, 다리 로봇 기본은 False)",
    )
    parser.add_argument("--trials", type=int, default=5, help="바닥 후보 지점 중 시도할 개수")
    parser.add_argument("--steps", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log", default=None, help="결과 JSON 저장 경로 (선택)")
    return parser.parse_args()


def main():
    args = parse_args()

    from scene3d.legged import (
        BUILTIN_SPECS,
        hold_home_pose,
        load_legged_robot,
        run_stance_trial,
        spec_from_urdf,
    )
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import resolve_source

    t0 = time.time()
    try:
        source = resolve_source(args.source, split=args.split)
    except Exception as e:
        print(f"오류: 입력 판별/해석 실패 — {e}")
        sys.exit(1)

    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    spots, floor_z = find_free_floor_spots(cid, lo, hi)
    if not spots:
        print("오류: 씬에서 빈 바닥 지점을 찾지 못함")
        sys.exit(1)
    print(f"씬 준비 완료: {source.scene_id} ({time.time()-t0:.1f}s), "
          f"바닥 후보 {len(spots)}개, floor_z={floor_z:.3f}")

    if args.urdf:
        spec = spec_from_urdf(cid, args.urdf, name=os.path.basename(args.urdf))
        print(f"임의 URDF로 자동 스펙 생성: {spec.name} "
              f"(관절 {len(spec.joint_types)}개, spawn_height={spec.spawn_height})")
    else:
        spec = BUILTIN_SPECS[args.robot]

    rng = np.random.default_rng(args.seed)
    n_trials = min(args.trials, len(spots))
    idx_pool = rng.choice(len(spots), size=n_trials, replace=False)

    results = []
    n_pass = 0
    for i, idx in enumerate(idx_pool):
        x, y = spots[int(idx)]
        rid = load_legged_robot(cid, spec, (x, y), floor_z, fixed_base=args.fixed_base)
        hold_home_pose(cid, rid, spec)
        trial = run_stance_trial(cid, rid, spec, steps=args.steps)
        p.removeBody(rid, physicsClientId=cid)

        n_pass += trial.verdict == "PASS"
        print(f"  [{i}] spot=({x:.2f},{y:.2f}) verdict={trial.verdict:4s} "
              f"min_h={trial.min_base_height:.3f} max_tilt={trial.max_tilt_deg:.1f}deg "
              f"fell_at={trial.fell_at_step}")
        results.append({
            "spot": [x, y], "verdict": trial.verdict,
            "min_base_height": trial.min_base_height,
            "max_tilt_deg": trial.max_tilt_deg,
            "fell_at_step": trial.fell_at_step,
        })

    print(f"\n요약: {spec.name} — PASS {n_pass}/{n_trials} "
          f"({100*n_pass/n_trials:.0f}%)")

    if args.log:
        os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
        with open(args.log, "w") as f:
            json.dump({
                "scene_id": source.scene_id, "robot": spec.name,
                "steps": args.steps, "results": results,
                "pass_rate": n_pass / n_trials,
            }, f, indent=2)
        print(f"결과 저장: {args.log}")

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
