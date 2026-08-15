"""test_p21 — quadruped/humanoid stance(정적 자립) 실패 탐색 검증.

1) 순수 legged.py 단위 검증(HM3D 데이터셋 불필요): laikago/humanoid URDF가
   기대한 관절 수로 로드되는지, 평평한 바닥 위에서 run_stance_trial이 결정론적
   PASS를 내는지, spec_from_urdf()로 임의 URDF(quadruped.urdf)도 같은 경로로
   동작하는지 확인한다.
2) HM3D 실제 씬 검증(데이터셋 없으면 skip): 실제 스캔 바닥 지점에서 stance
   trial이 실제로 물리 스텝을 진행하는지, 씬 경계(벽 근처)에 스폰하면 FAIL이
   실제로 감지되는지 확인한다.

실행:
  uv run --extra scene3d python tests/test_p21_legged_stance.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pybullet as p
import pybullet_data


def test_unit_no_hm3d():
    from scene3d.legged import (
        HUMANOID_SPEC,
        LAIKAGO_SPEC,
        hold_home_pose,
        load_legged_robot,
        run_stance_trial,
        spec_from_urdf,
    )

    # laikago: 12개 revolute leg joint + 4개 fixed toe = 16 joint
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.loadURDF("plane.urdf", physicsClientId=cid)
    rid = load_legged_robot(cid, LAIKAGO_SPEC, (0.0, 0.0), floor_z=0.0)
    assert p.getNumJoints(rid, physicsClientId=cid) == 16
    hold_home_pose(cid, rid, LAIKAGO_SPEC)
    result = run_stance_trial(cid, rid, LAIKAGO_SPEC, steps=240)
    assert result.verdict == "PASS", f"laikago가 평평한 바닥에서도 넘어짐: {result}"
    assert len(result.base_path) == 240
    assert result.max_tilt_deg < 10.0, f"laikago 기립이 예상보다 불안정: {result.max_tilt_deg}"
    p.disconnect(physicsClientId=cid)
    print(f"[1] laikago 평지 PASS 확인: min_h={result.min_base_height:.3f} "
          f"max_tilt={result.max_tilt_deg:.2f}deg")

    # humanoid: 15개 joint (spherical 8 + revolute 4 + fixed 3)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.loadURDF("plane.urdf", physicsClientId=cid)
    rid = load_legged_robot(cid, HUMANOID_SPEC, (0.0, 0.0), floor_z=0.0)
    assert p.getNumJoints(rid, physicsClientId=cid) == 15
    hold_home_pose(cid, rid, HUMANOID_SPEC)
    result = run_stance_trial(cid, rid, HUMANOID_SPEC, steps=240)
    assert result.verdict == "PASS", f"humanoid가 평평한 바닥에서도 넘어짐: {result}"
    assert len(result.base_path) == 240
    p.disconnect(physicsClientId=cid)
    print(f"[2] humanoid 평지 PASS 확인: min_h={result.min_base_height:.3f} "
          f"max_tilt={result.max_tilt_deg:.2f}deg")

    # 임의 URDF(quadruped.urdf) — 전용 SPEC 없이 spec_from_urdf()로 자동 구성
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.loadURDF("plane.urdf", physicsClientId=cid)
    spec = spec_from_urdf(cid, "quadruped/quadruped.urdf", name="quadruped_auto")
    assert len(spec.joint_types) > 0, "spec_from_urdf가 비고정 관절을 하나도 못 찾음"
    rid = load_legged_robot(cid, spec, (0.0, 0.0), floor_z=0.0)
    hold_home_pose(cid, rid, spec)
    result = run_stance_trial(cid, rid, spec, steps=240)
    assert result.verdict in ("PASS", "FAIL")
    assert len(result.base_path) == 240
    p.disconnect(physicsClientId=cid)
    print(f"[3] 임의 URDF(quadruped) 자동 스펙 동작 확인: verdict={result.verdict} "
          f"(관절 {len(spec.joint_types)}개)")


def test_hm3d_scene():
    from scene3d.hm3d_dataset import DEFAULT_DATASET_DIR

    if not os.path.isdir(DEFAULT_DATASET_DIR):
        print(f"SKIP: HM3D 데이터셋 없음 ({DEFAULT_DATASET_DIR})")
        return

    from scene3d.legged import LAIKAGO_SPEC, hold_home_pose, load_legged_robot, run_stance_trial
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.sources import resolve_source

    source = resolve_source("00802", split="minival")
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    spots, floor_z = find_free_floor_spots(cid, lo, hi)
    assert len(spots) > 0, "빈 바닥 지점을 하나도 못 찾음"

    # 1) 실제 씬의 정상 바닥 지점 — 물리 스텝이 실제로 진행되는지만 확인
    #    (특정 지점의 PASS/FAIL은 지형에 따라 달라질 수 있어 결정론적으로 강제하지 않음)
    x, y = spots[0]
    rid = load_legged_robot(cid, LAIKAGO_SPEC, (x, y), floor_z)
    hold_home_pose(cid, rid, LAIKAGO_SPEC)
    result = run_stance_trial(cid, rid, LAIKAGO_SPEC, steps=240)
    assert result.verdict in ("PASS", "FAIL")
    assert len(result.base_path) == 240
    p.removeBody(rid, physicsClientId=cid)
    print(f"[4] HM3D 정상 지점 stance trial 동작 확인: verdict={result.verdict} "
          f"spot=({x:.2f},{y:.2f})")

    # 2) 의도적으로 씬 경계(벽 근처)에 스폰 — FAIL이 실제로 감지되는지 확인
    bad_x, bad_y = float(lo[0]) + 0.05, float(lo[1]) + 0.05
    rid_bad = load_legged_robot(cid, LAIKAGO_SPEC, (bad_x, bad_y), floor_z)
    hold_home_pose(cid, rid_bad, LAIKAGO_SPEC)
    bad_result = run_stance_trial(cid, rid_bad, LAIKAGO_SPEC, steps=240)
    assert bad_result.verdict == "FAIL", (
        f"씬 경계(벽 근처)에 스폰했는데도 FAIL이 감지되지 않음: {bad_result}"
    )
    print(f"[5] 씬 경계 스폰 FAIL 감지 확인: fell_at={bad_result.fell_at_step} "
          f"max_tilt={bad_result.max_tilt_deg:.1f}deg")

    p.disconnect(physicsClientId=cid)


def main():
    test_unit_no_hm3d()
    test_hm3d_scene()
    print("\ntest_p21 PASS")


if __name__ == "__main__":
    main()
