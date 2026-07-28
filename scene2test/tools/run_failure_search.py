"""run_hm3d_search.py — HM3D 실제 씬에서 Active Failure Search 실행.

흐름: 씬 1회 로드 + 작업공간 구성 (Phase 3)
      → 로봇-로컬 SceneGraph로 기존 탐색 엔진 구동 (surrogate + acquisition)
      → mutation은 body teleport로 적용 (재로드 없음, 테스트당 ~0.1s)

사용:
  # Active (cold) 탐색
  PYBULLET_MODE=DIRECT uv run python tools/run_hm3d_search.py \
      --scene 00800 --mode cold --rounds 4 --tests-per-round 12

  # Random vs Active 비교
  PYBULLET_MODE=DIRECT uv run python tools/run_hm3d_search.py \
      --scene 00800 --mode compare --rounds 4 --tests-per-round 12

출력: data/hm3d_search_logs/search_*.json
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
    parser = argparse.ArgumentParser(description="HM3D Active Failure Search")
    parser.add_argument("--scene", default="00800", help="씬 참조 (semantic 보유 씬)")
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--surface", type=int, default=-1, help="지지면 인덱스 (-1=자동)")
    parser.add_argument("--mode", default="cold", choices=["cold", "random", "compare"])
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--tests-per-round", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-dir", default="data/hm3d_search_logs")
    return parser.parse_args()


def main():
    args = parse_args()

    from active_failure_search import SearchConfig
    from hm3d.dataset import HM3DDataset
    from hm3d.failure_search import (
        HM3DFailureSearch,
        HM3DSearchSession,
        run_hm3d_comparison,
    )
    from hm3d.loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_hm3d_static,
        scene_extent_pybullet,
    )
    from hm3d.semantics import build_scene_graph, extract_instances
    from hm3d.workspace import WorkspacePlacementError, setup_workspace
    from physical_oracle import load_thresholds
    from sim_runner import load_robot_config

    # ── 씬 + 작업공간 1회 구성 ──────────────────────────────────────────
    t0 = time.time()
    ds = HM3DDataset(split=args.split)
    extracted = ds.extract(args.scene)
    entry = extracted.entry
    if extracted.semantic_glb_path is None:
        print(f"오류: {entry.scene_dir}에는 semantic annotation이 없습니다.")
        sys.exit(1)

    converted = convert_glb_to_obj(extracted.glb_path, entry.scene_dir)
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_hm3d_static(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    instances = extract_instances(
        extracted.semantic_glb_path, extracted.semantic_txt_path,
        offset=converted.offset,
    )
    sg = build_scene_graph(instances, scene_id=entry.scene_dir, include_structural=True)
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

    session = HM3DSearchSession.create(ws, cid)
    print(f"씬 준비 완료: {entry.scene_dir} {ws.surface.id} "
          f"({time.time()-t0:.1f}s)")
    print(f"  로봇 베이스(월드): {np.round(ws.robot_base_pos, 2).tolist()}, "
          f"로컬 프레임 θ={np.degrees(session.frame.theta):.0f}°")

    thresholds = load_thresholds("config/thresholds.yaml")

    # ── 탐색 ────────────────────────────────────────────────────────────
    if args.mode == "compare":
        run_hm3d_comparison(
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
        search = HM3DFailureSearch(session, thresholds, cfg)
        search.run()
        summary = search.summary()
        print("\n요약:", summary)

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
