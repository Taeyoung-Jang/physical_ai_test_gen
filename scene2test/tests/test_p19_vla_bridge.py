"""test_p19 — VLA closed-loop을 scene3d 세션 위에서 실행하는 다리(vla_bridge) 검증.

HM3D 데이터셋(tar)이 없는 환경에서는 skip한다. StubReachPolicy(GPU 불필요)로
검증하므로 실제 OpenVLA 다운로드는 필요 없다.

실행:
  PYBULLET_MODE=DIRECT uv run --extra scene3d python tests/test_p19_vla_bridge.py
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

    import scene_builder
    from physical_oracle import load_thresholds
    from policies_vla import StubReachPolicy
    from scene3d.failure_search import SceneSearchSession
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import generate_scene_graph, resolve_source
    from scene3d.vla_bridge import run_closed_loop_on_session
    from scene3d.workspace_setup import run_case, setup_workspace_auto
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
    session = SceneSearchSession.create(ws, cid)
    scene_builder._client_id = cid
    print(f"[1] 세션 준비 OK: {ws.surface.id}, 베이스 {np.round(ws.robot_base_pos,2).tolist()}")

    # 2) VLA closed-loop 실행(mutation 없이 base case) — 재로드 없이 세션 재사용
    policy = StubReachPolicy(seed=0)
    trace = run_closed_loop_on_session(
        session, policy, session.local_sg,
        instruction="pick up the target", case_id="test_p19_base", max_steps=40,
    )
    assert trace.execution_mode == "lam_vla"
    assert len(trace.ee_path) > 0, "ee_path가 비어 있음 — 스텝이 한 번도 안 돔"
    moved = float(np.linalg.norm(np.array(trace.ee_path[-1]) - np.array(trace.ee_path[0])))
    assert moved > 0.05, f"로봇이 거의 안 움직임(moved={moved:.4f}m) — 카메라/IK 연결 의심"
    print(f"[2] VLA rollout OK: {len(trace.ee_path)} steps, 이동 {moved:.3f}m, "
          f"reach_margin={trace.reach_margin:.3f}, grasp={trace.grasp_success}")

    # 3) 좌표계 검증: reach_margin이 합리적 범위(로봇 max_reach 이내)여야 함 —
    #    프레임 회전이 틀렸다면 이 값이 크게 음수로 나온다(과거 버그: -0.67).
    max_reach = robot_cfg["robot"]["max_reach"]
    assert -max_reach <= trace.reach_margin <= max_reach, \
        f"reach_margin={trace.reach_margin:.3f}이 비정상 — 프레임 변환 오류 의심"
    print(f"[3] 좌표계 OK: reach_margin={trace.reach_margin:.3f} (범위 ±{max_reach})")

    # 4) 오라클 경로와 대조 — 같은 베이스 케이스에서 극단적으로 다른 판정이면
    #    카메라/좌표 버그를 의심할 신호(완전히 unreachable인데 VLA만 도달 등)
    thresholds = load_thresholds("config/thresholds.yaml")
    oracle, kin = run_case(ws, thresholds)
    print(f"[4] 오라클 대조: oracle verdict={oracle.verdict} "
          f"robustness={oracle.robustness*100:.1f}cm / "
          f"VLA reach_margin={trace.reach_margin*100:.1f}cm")
    # oracle이 PASS 근처인데 VLA reach_margin이 극단적으로 음수(-0.5m 이상 미달)면
    # 이상 신호로 본다. 정확한 grasp 수렴은 스텁 컨트롤러 품질에 달려 있어 요구하지
    # 않는다 — 이 테스트는 "다리(bridge)"가 맞물려 있는지만 검증한다.
    if oracle.robustness > -0.05:
        assert trace.reach_margin > -0.3, (
            f"오라클은 거의 성공권({oracle.robustness*100:.1f}cm)인데 "
            f"VLA reach_margin이 크게 벗어남({trace.reach_margin*100:.1f}cm) — "
            "프레임/카메라 버그 의심"
        )

    p.disconnect(physicsClientId=cid)
    print("\ntest_p19 PASS")


if __name__ == "__main__":
    main()
