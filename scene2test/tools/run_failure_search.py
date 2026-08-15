"""run_failure_search.py — 3D scene 위에서 Active Failure Search 실행.

흐름: 씬 1회 로드 + 작업공간 구성 (workspace_setup 재사용)
      → 로봇-로컬 SceneGraph로 기존 탐색 엔진 구동 (surrogate + acquisition)
      → mutation은 body teleport로 적용 (재로드 없음, 테스트당 ~0.1s)

두 가지 평가 방식(--evaluator):
  oracle (기본) : kinematic oracle(IK 도달성 + 거리 쿼리)로 판정. 빠름(~0.1s/test).
  vla           : 실제 정책(VLA)을 RGB→act→IK→step으로 실제 실행해 판정
                  (scene3d.vla_bridge, lam_guided.policy_oracle 재사용). oracle보다
                  느리지만 IK만으로는 못 잡는 실제 행동 실패를 관찰할 수 있다.

사용:
  # Active (cold) 탐색 — kinematic oracle
  PYBULLET_MODE=DIRECT uv run python tools/run_failure_search.py \
      --source 00800 --mode cold --rounds 4 --tests-per-round 12

  # Random vs Active 비교
  PYBULLET_MODE=DIRECT uv run python tools/run_failure_search.py \
      --source 00800 --mode compare --rounds 4 --tests-per-round 12

  # robot base pose도 탐색 변수로 (같은 작업 배치를 다른 위치에서 시도)
  PYBULLET_MODE=DIRECT uv run python tools/run_failure_search.py \
      --source 00800 --mode cold --vary-base-pose

  # VLA closed-loop 평가 (GPU 불필요, StubReachPolicy로 스모크 테스트)
  PYBULLET_MODE=DIRECT uv run python tools/run_failure_search.py \
      --source 00800 --evaluator vla --vla stub --rounds 1 --tests-per-round 5

  # 실제 OpenVLA로 교체 (uv sync --extra vla 필요, ~15GB 다운로드)
  PYBULLET_MODE=DIRECT uv run python tools/run_failure_search.py \
      --source 00800 --evaluator vla --vla openvla

출력: data/scene3d_search_logs/search_*.json
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="3D scene Active Failure Search")
    parser.add_argument(
        "--source", default="00800",
        help="HM3D scene id | mesh 파일 경로(.glb/.obj/.ply) | SceneGraph JSON 경로",
    )
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--surface", type=int, default=-1, help="지지면 인덱스 (-1=자동)")
    parser.add_argument("--mode", default="cold", choices=["cold", "random", "compare"])
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--tests-per-round", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-dir", default="data/scene3d_search_logs")
    parser.add_argument(
        "--vary-base-pose", action="store_true",
        help="로봇 base pose도 탐색 변수로 포함 (기본은 고정 — --evaluator oracle 전용)",
    )
    parser.add_argument("--evaluator", default="oracle", choices=["oracle", "vla"])
    parser.add_argument(
        "--vla", default="stub", choices=["stub", "openvla"],
        help="--evaluator vla일 때 쓸 정책. stub=GPU 불필요, openvla=실제 OpenVLA-7B",
    )
    parser.add_argument(
        "--instruction", default="pick up the target",
        help="--evaluator vla일 때 VLA에 줄 명령 프롬프트",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    from active_failure_search import SearchConfig
    from physical_oracle import load_thresholds
    from scene3d.failure_search import (
        SceneFailureSearch,
        SceneSearchSession,
        run_scene_comparison,
    )
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import generate_scene_graph, resolve_source
    from scene3d.workspace_setup import WorkspacePlacementError, setup_workspace
    from sim_runner import load_robot_config

    # ── 씬 + 작업공간 1회 구성 ──────────────────────────────────────────
    t0 = time.time()
    try:
        source = resolve_source(args.source, split=args.split)
    except Exception as e:
        print(f"오류: 입력 판별/해석 실패 — {e}")
        sys.exit(1)

    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)

    try:
        sg = generate_scene_graph(source, offset=converted.offset)
    except ValueError as e:
        print(f"오류: {e}")
        sys.exit(1)
    robot_cfg = load_robot_config("config/robot_config.yaml")

    candidates = (
        sg.support_surfaces if args.surface < 0 else [sg.support_surfaces[args.surface]]
    )
    ws = None
    for surf in candidates:
        try:
            ws = setup_workspace(
                converted, scene_ids, sg, surf.id, floor_z, robot_cfg, cid
            )
            break
        except WorkspacePlacementError:
            continue
    if ws is None:
        print("오류: 로봇 배치 실패")
        sys.exit(1)

    session = SceneSearchSession.create(ws, cid)
    print(f"씬 준비 완료: {source.scene_id} {ws.surface.id} "
          f"({time.time()-t0:.1f}s)")
    print(f"  로봇 베이스(월드): {np.round(ws.robot_base_pos, 2).tolist()}, "
          f"로컬 프레임 θ={np.degrees(session.frame.theta):.0f}°")

    thresholds = load_thresholds("config/thresholds.yaml")

    # ── 탐색 ────────────────────────────────────────────────────────────
    if args.evaluator == "vla":
        _run_vla_evaluator(session, thresholds, args)
    elif args.mode == "compare":
        run_scene_comparison(
            session, thresholds,
            rounds=args.rounds, tests_per_round=args.tests_per_round,
            seed=args.seed, log_dir=args.log_dir,
        )
    else:
        cfg = SearchConfig(
            num_rounds=args.rounds,
            tests_per_round=args.tests_per_round,
            mode=args.mode,
            seed=args.seed,
            log_dir=args.log_dir,
        )
        search = SceneFailureSearch(
            session, thresholds, cfg, vary_base_pose=args.vary_base_pose
        )
        search.run()
        summary = search.summary()
        print("\n요약:", summary)

    p.disconnect(physicsClientId=cid)


def _run_vla_evaluator(session, thresholds: dict, args) -> None:
    """--evaluator vla: 실제 정책을 closed-loop으로 실행해 판정.

    오라클 경로와 동일한 mutation_space 샘플러를 재사용해 후보를 뽑고,
    scene3d.vla_bridge.run_closed_loop_on_session()으로 실제 실행 →
    lam_guided.policy_oracle.evaluate_physical_from_trace()로 판정한다.
    surrogate/acquisition 기반 능동 탐색은 아직 없음(이번 스코프는 스모크
    테스트 — 오라클 경로처럼 실패를 능동적으로 조준하진 않는다).
    """
    import mutation_space
    import scene_builder
    from lam_guided.policy_oracle import evaluate_physical_from_trace
    from policies_vla import make_closed_loop_policy
    from scene3d.failure_search import _local_robot_cfg
    from scene3d.vla_bridge import run_closed_loop_on_session

    policy = make_closed_loop_policy(args.vla)
    local_robot_cfg = _local_robot_cfg(session.ws.robot_cfg)

    print(f"\n=== VLA closed-loop 평가 (policy={args.vla}) ===")
    n_total = 0
    n_fail = 0
    types: set[str] = set()
    for r in range(args.rounds):
        pool = mutation_space.sample_random(
            session.local_sg, local_robot_cfg,
            n=args.tests_per_round, seed=args.seed + r,
        )
        for i, params in enumerate(pool[:args.tests_per_round]):
            mutated_local = scene_builder.apply_mutation(session.local_sg, params)
            case_id = f"R{r:02d}_T{i:02d}_vla"
            trace = run_closed_loop_on_session(
                session, policy, mutated_local, args.instruction, case_id,
            )
            phys = evaluate_physical_from_trace(trace, thresholds)
            n_total += 1
            if phys.verdict in ("FAIL", "BLOCKED"):
                n_fail += 1
                types.update(phys.failure_types)
            print(f"  {case_id}: verdict={phys.verdict:6s} grasp={trace.grasp_success!s:5s} "
                  f"reach_margin={trace.reach_margin:+.3f} "
                  f"obstacle_dist={trace.path_min_obstacle_dist:+.3f} "
                  f"failure_types={phys.failure_types}")

    print(f"\n요약: FAIL/BLOCKED {n_fail}/{n_total}, failure_types={sorted(types)}")


if __name__ == "__main__":
    main()
