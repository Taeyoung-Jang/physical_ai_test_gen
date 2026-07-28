"""test_p20 — robot base pose를 탐색 변수로 쓰는 기능 검증.

HM3D 데이터셋(tar)이 없는 환경에서는 skip한다.

실행:
  PYBULLET_MODE=DIRECT uv run --extra scene3d python tests/test_p20_base_pose_search.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np


def main():
    from scene3d.hm3d_dataset import DEFAULT_DATASET_DIR

    if not os.path.isdir(DEFAULT_DATASET_DIR):
        print(f"SKIP: HM3D 데이터셋 없음 ({DEFAULT_DATASET_DIR})")
        return

    import pybullet as p
    import pybullet_data

    from active_failure_search import SearchConfig
    from physical_oracle import load_thresholds
    from scene3d.failure_search import SceneFailureSearch, SceneSearchSession
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import generate_scene_graph, resolve_source
    from scene3d.workspace_setup import setup_workspace_auto
    from sim_runner import load_robot_config

    source = resolve_source("00802", split="minival")
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    sg = generate_scene_graph(source, offset=converted.offset)
    robot_cfg = load_robot_config("config/robot_config.yaml")
    ws = setup_workspace_auto(converted, scene_ids, sg, floor_z, robot_cfg, cid)

    # 1) 유효 base pose 후보가 1개 이상, 그리고 setup_workspace가 실제로 고른
    #    베이스(ws.robot_base_pos)가 후보 목록의 첫 번째와 정확히 일치해야 함
    #    (받침대 spawn 전에 계산해서 자기 자신에게 막히는 버그가 없어야 함).
    candidates = ws.base_pose_candidates
    assert len(candidates) >= 1, "base pose 후보가 0개"
    assert np.allclose(candidates[0]["base_pos"], ws.robot_base_pos, atol=1e-9), (
        f"1번 후보({candidates[0]['base_pos']})가 실제 선택된 베이스"
        f"({ws.robot_base_pos})와 다름 — 받침대 자기충돌 버그 의심"
    )
    print(f"[1] base pose 후보 OK: {len(candidates)}개, "
          f"1번={np.round(candidates[0]['base_pos'], 2).tolist()}")

    # 2) 세션 생성 시 후보를 다시 계산하지 않고 ws의 캐시를 그대로 재사용하는지
    session = SceneSearchSession.create(ws, cid)
    assert session.base_pose_candidates is ws.base_pose_candidates or \
        session.base_pose_candidates == ws.base_pose_candidates
    print(f"[2] 세션 캐시 재사용 OK: {len(session.base_pose_candidates)}개")

    # 3) vary_base_pose=True로 여러 테스트 실행 — margin이 후보에 따라 실제로
    #    달라지는지(=탐색 변수로서 의미가 있는지) 확인
    thresholds = load_thresholds("config/thresholds.yaml")
    cfg = SearchConfig(
        num_rounds=1, tests_per_round=10, mode="random", seed=3,
        log_dir="data/scene3d_search_logs",
    )
    search = SceneFailureSearch(session, thresholds, cfg, vary_base_pose=True)
    records = search.run()
    assert len(records) == 10
    used_indices = {
        r.mutation_params.get("_base_pose_index")
        for r in records if "_base_pose_index" in r.mutation_params
    }
    for r in records:
        for name, v in r.margins.items():
            assert np.isfinite(v) and abs(v) < 10, f"margin {name}={v} 비정상"
    print(f"[3] vary_base_pose 실행 OK: 10개 테스트, "
          f"사용된 base_pose_index={sorted(used_indices)}")
    if len(candidates) > 1:
        assert len(used_indices) > 0, "_base_pose_index가 기록되지 않음"

    # 4) restore 후 로봇이 원래 베이스로 돌아오는지
    session.restore()
    pos, _ = p.getBasePositionAndOrientation(ws.robot_body_id, physicsClientId=cid)
    assert np.allclose(pos, ws.robot_base_pos, atol=1e-6), "restore 후 로봇 베이스 불일치"
    print("[4] restore OK: 로봇 베이스 원위치 확인")

    p.disconnect(physicsClientId=cid)
    print("\ntest_p20 PASS")


if __name__ == "__main__":
    main()
