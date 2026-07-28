"""test_p17 — 3D scene 위 Active Failure Search 검증.

HM3D 데이터셋(tar)이 없는 환경에서는 E2E 파트를 skip한다.

실행:
  PYBULLET_MODE=DIRECT uv run --extra scene3d python tests/test_p17_failure_search.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np


def test_local_frame():
    """LocalFrame 왕복 변환 + 축정렬 회전 크기 교환."""
    from scene3d.failure_search import LocalFrame

    for theta in (0.0, math.pi / 2, math.pi, -math.pi / 2):
        f = LocalFrame(base_xy=np.array([3.0, -2.0]), base_z=0.9, theta=theta)
        p_world = [3.7, -1.4, 1.1]
        back = f.to_world(f.to_local(p_world))
        assert np.allclose(back, p_world, atol=1e-9), f"왕복 실패 θ={theta}"

    # 90° 회전이면 x/y 크기 교환
    f90 = LocalFrame(base_xy=np.zeros(2), base_z=0.0, theta=math.pi / 2)
    assert f90.size_to_local([0.1, 0.2, 0.3]) == [0.2, 0.1, 0.3]
    f0 = LocalFrame(base_xy=np.zeros(2), base_z=0.0, theta=0.0)
    assert f0.size_to_local([0.1, 0.2, 0.3]) == [0.1, 0.2, 0.3]
    print("[1] LocalFrame OK (왕복 + 크기 교환)")


def test_hm3d_search_e2e():
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
    from scene3d.robot_workspace import setup_workspace_auto
    from scene3d.sources import generate_scene_graph, resolve_source
    from sim_runner import load_robot_config

    source = resolve_source("00800", split="minival")
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    sg = generate_scene_graph(source, offset=converted.offset)
    robot_cfg = load_robot_config("config/robot_config.yaml")
    ws = setup_workspace_auto(converted, scene_ids, sg, floor_z, robot_cfg, cid)
    session = SceneSearchSession.create(ws, cid)

    # 2) 로컬 SceneGraph: 로봇 기준 프레임 불변식
    local_sg = session.local_sg
    t_local = np.array(local_sg.target().position)
    assert t_local[0] > 0.2, "로컬 프레임에서 target은 +x 전방이어야"
    assert abs(t_local[1]) < 0.4
    obstacles = local_sg.obstacles()
    assert obstacles[1].id == "occupant_block", "obstacles[1]은 tray 점유용이어야"
    print(f"[2] 로컬 SceneGraph OK: target={np.round(t_local, 2).tolist()}")

    # 3) 탐색 실행 (random 1라운드 — surrogate 무관 경로)
    thresholds = load_thresholds("config/thresholds.yaml")
    cfg = SearchConfig(
        num_rounds=1, tests_per_round=5, mode="random", seed=7,
        log_dir="data/scene3d_search_logs",
    )
    search = SceneFailureSearch(session, thresholds, cfg)
    records = search.run()
    assert len(records) == 5
    for rec in records:
        assert rec.verdict in ("PASS", "WARN", "FAIL", "BLOCKED")
        assert len(rec.feature_vector) == 16, "16차원 feature"
        for name, v in rec.margins.items():
            assert np.isfinite(v) and abs(v) < 10, f"margin {name}={v}"
    print("[3] 탐색 OK: 5개 테스트, margin/feature 정상")

    # 4) restore: spawn body들이 초기 위치로 복귀
    session.restore()
    t_pos, _ = p.getBasePositionAndOrientation(
        ws.body_map["target_block"], physicsClientId=cid
    )
    assert np.allclose(t_pos, ws.target_pos, atol=1e-6), "restore 실패"
    print("[4] restore OK")

    p.disconnect(physicsClientId=cid)


def main():
    test_local_frame()
    test_hm3d_search_e2e()
    print("\ntest_p17 PASS")


if __name__ == "__main__":
    main()
