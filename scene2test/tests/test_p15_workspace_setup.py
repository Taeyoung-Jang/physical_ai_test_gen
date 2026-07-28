"""test_p15 — 3D scene 작업공간 + oracle E2E 검증.

HM3D 데이터셋(tar)이 없는 환경에서는 전체를 skip한다.

실행:
  PYBULLET_MODE=DIRECT uv run --extra scene3d python tests/test_p15_workspace_setup.py
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

    from physical_oracle import Verdict, load_thresholds
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import generate_scene_graph, resolve_source
    from scene3d.workspace_setup import run_case, setup_workspace_auto
    from sim_runner import load_robot_config

    # 입력 판별(Stage 1 진입점)부터 실제로 거쳐서 검증한다 — HM3D scene id를
    # 넣으면 sources.resolve_source가 알아서 hm3d 백엔드로 위임해야 한다.
    source = resolve_source("00800", split="minival")
    assert source.kind == "hm3d"
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)

    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    # setup_workspace는 표준 SceneGraph만 받는다 — HM3D가 만들었든, 저장된
    # JSON을 다시 읽었든, 다른 파이프라인 산출물이든 동일하게 동작해야 한다.
    sg = generate_scene_graph(source, offset=converted.offset)
    robot_cfg = load_robot_config("config/robot_config.yaml")

    # 1. 작업공간 구성 (배치 가능한 지지면 폴백)
    ws = setup_workspace_auto(converted, scene_ids, sg, floor_z, robot_cfg, cid)
    print(f"[1] 작업공간 OK: {ws.surface.id}, "
          f"베이스 {np.round(ws.robot_base_pos, 2).tolist()}")

    # 2. 배치 기하 검증
    top = ws.surface.top_z
    base = np.array(ws.robot_base_pos)
    assert abs(base[2] - (top - 0.10)) < 1e-6, "베이스 높이 = 상면 - BASE_DROP"
    for key in ("target_block", "obstacle_block", "tray"):
        assert key in ws.body_map, f"{key} 미생성"
    target = np.array(ws.target_pos)
    reach_xy = float(np.linalg.norm(target[:2] - base[:2]))
    assert 0.30 <= reach_xy <= 0.64, f"target 수평 도달 거리 {reach_xy:.2f}"
    assert abs(target[2] - (top + 0.03)) < 1e-6, "target은 상면 위"
    print(f"[2] 배치 기하 OK: 도달 {reach_xy:.2f}m, target z={target[2]:.2f}")

    # 3. SceneGraph: spawn 3종 + 주변 컨텍스트 객체
    roles = {o.role for o in ws.sg.objects}
    assert {"target", "obstacle", "destination"} <= roles
    ctx = [o for o in ws.sg.objects if o.extra.get("hm3d_context")]
    assert len(ctx) > 0, "주변 컨텍스트 객체 없음"
    print(f"[3] SceneGraph OK: 객체 {len(ws.sg.objects)}개 (컨텍스트 {len(ctx)}개)")

    # 4. oracle 실행 — margin이 전부 유한하고 verdict가 유효해야 함
    thresholds = load_thresholds("config/thresholds.yaml")
    oracle, kin = run_case(ws, thresholds)
    assert kin.ik_success, "IK 실패"
    assert oracle.verdict in (Verdict.PASS, Verdict.WARN, Verdict.FAIL, Verdict.BLOCKED)
    for name, v in oracle.margins.items():
        assert np.isfinite(v), f"margin {name} 비정상: {v}"
        assert abs(v) < 10.0, f"margin {name} 비정상 크기: {v} (concave 거리 쿼리 오염?)"
    assert oracle.margins["safety"] > 0, "human zone 없으므로 safety 여유"
    print(f"[4] Oracle OK: verdict={oracle.verdict} "
          f"robustness={oracle.robustness*100:.1f}cm binding={oracle.binding_margin}")

    p.disconnect(physicsClientId=cid)
    print("\ntest_p15 PASS")


if __name__ == "__main__":
    main()
