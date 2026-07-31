"""animate_stance.py — 다리 로봇(quadruped/humanoid) stance 시뮬레이션을 GIF로 저장.

run_stance_test.py는 판정(PASS/FAIL)만 출력하고 영상은 안 남긴다 — 이 도구는
tools/animate_failure.py(팔 애니메이션)와 같은 목적을 legged 로봇에 적용한 것으로,
실제 물리 스텝(중력 + position-hold 모터)이 진행되는 동안 매 스텝 카메라로 찍어
GIF로 모은다. 로봇이 실제로 서 있는지/넘어지는지 눈으로 확인하는 용도.

기본은 pybullet_data의 빈 평면 위에서 돌린다 — HM3D 실내 스캔은 좁고 어수선해
로봇이 가구에 가려지거나 카메라가 벽을 뚫고 들어가기 쉽다(실측으로 확인됨:
클러터 씬에서는 로봇이 잘 안 보임). 실제 스캔 씬 안에서 보고 싶으면 --source를
지정한다(배경은 어수선할 수 있음).

사용:
  # 평지에서 깨끗하게 서는 모습
  uv run python tools/animate_stance.py --robot laikago \
      --output data/scene3d_stance_gifs/laikago_stand.gif

  # 일부러 앞/뒤 다리 자세를 다르게 줘서 넘어지는 모습 (실패 탐색이 실제로 잡아내는 종류)
  uv run python tools/animate_stance.py --robot laikago --bad-pose \
      --output data/scene3d_stance_gifs/laikago_fall.gif

  # 실제 HM3D 씬 안에서 (배경은 어수선할 수 있음)
  PYBULLET_MODE=DIRECT uv run python tools/animate_stance.py \
      --source 00802 --robot humanoid \
      --output data/scene3d_stance_gifs/humanoid_scene.gif
"""
from __future__ import annotations

import argparse
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import imageio
import numpy as np
import pybullet as p
import pybullet_data


def parse_args():
    parser = argparse.ArgumentParser(description="Legged 로봇 stance 애니메이션 GIF 생성")
    parser.add_argument(
        "--source", default=None,
        help="지정 시 HM3D 씬/mesh 위에서 실행 (기본: 빈 평면)",
    )
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--robot", default="laikago", choices=["laikago", "humanoid"])
    parser.add_argument("--urdf", default=None, help="지정 시 --robot 대신 임의 URDF 사용")
    parser.add_argument(
        "--bad-pose", action="store_true",
        help="앞/뒤 다리(또는 좌우 hip) 자세를 비대칭으로 줘서 일부러 넘어뜨림 — 실패 시연용",
    )
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--stride", type=int, default=2, help="이 스텝마다 1프레임 캡처")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--output", default="data/scene3d_stance_gifs/stance.gif")
    parser.add_argument("--width", type=int, default=400)
    parser.add_argument("--height", type=int, default=300)
    return parser.parse_args()


def capture_frame(cid, target, width, height, yaw, distance, pitch):
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=target, distance=distance,
        yaw=yaw, pitch=pitch, roll=0, upAxisIndex=2, physicsClientId=cid,
    )
    proj = p.computeProjectionMatrixFOV(
        fov=55, aspect=width / height, nearVal=0.05, farVal=20.0, physicsClientId=cid,
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, lightDirection=[1, 1, 1],
        lightAmbientCoeff=0.7, lightDiffuseCoeff=0.5, lightSpecularCoeff=0.05,
        shadow=1, physicsClientId=cid,
    )
    return np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()


def _make_bad_pose_spec(spec):
    """앞/뒤(또는 좌/우) 다리를 비대칭으로 만들어 넘어짐을 유도한 spec 사본.

    laikago: 뒷다리 두 개를 곧게 편 자세로 바꿔 앞뒤 지지 높이를 다르게 만든다.
    humanoid: 한쪽 hip만 앞으로 크게 굽혀 무게중심을 한쪽으로 쏠리게 한다.
    """
    bad = copy.deepcopy(spec)
    if spec.name == "laikago":
        for j in (8, 9, 10, 12, 13, 14):  # RR/RL 다리 = 곧게
            bad.home_positions[j] = [0.0]
    elif spec.name == "humanoid":
        bad.home_positions[9] = list(p.getQuaternionFromEuler([0, 0.9, 0]))  # right_hip 크게 굽힘
    return bad


def main():
    args = parse_args()

    from scene3d.legged import BUILTIN_SPECS, hold_home_pose, load_legged_robot

    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)

    if args.source:
        from scene3d.mesh_loader import (
            convert_glb_to_obj,
            find_free_floor_spots,
            load_static_scene,
            scene_extent_pybullet,
        )
        from scene3d.sources import resolve_source

        source = resolve_source(args.source, split=args.split)
        converted = convert_glb_to_obj(source.glb_path, source.scene_id)
        load_static_scene(converted, cid, collision=True)
        lo, hi = scene_extent_pybullet(converted)
        spots, floor_z = find_free_floor_spots(cid, lo, hi)
        if not spots:
            print("오류: 빈 바닥 지점을 찾지 못함")
            sys.exit(1)
        x, y = spots[0]
        scene_label = source.scene_id
    else:
        p.loadURDF("plane.urdf", physicsClientId=cid)
        x, y, floor_z = 0.0, 0.0, 0.0
        scene_label = "flat_ground"

    if args.urdf:
        from scene3d.legged import spec_from_urdf as _spec_from_urdf
        spec = _spec_from_urdf(cid, args.urdf, name=os.path.basename(args.urdf))
    else:
        spec = BUILTIN_SPECS[args.robot]
    if args.bad_pose:
        spec = _make_bad_pose_spec(spec)

    rid = load_legged_robot(cid, spec, (x, y), floor_z)
    hold_home_pose(cid, rid, spec)

    print(f"씬={scene_label} 로봇={spec.name} spot=({x:.2f},{y:.2f}) bad_pose={args.bad_pose}")

    # 카메라 거리/높이를 로봇 크기(spawn_height)에 비례시킨다 — laikago(0.45m)에서
    # 잘 나온 distance=1.4/target_frac=0.35를 기준 비율로 삼아 humanoid(1.0m) 등
    # 더 큰 로봇도 몸통이 잘리지 않게 자동으로 멀어진다.
    scale = spec.spawn_height / 0.45
    cam_distance = 1.4 * scale
    target_frac = 0.35 * scale

    frames = []
    for step in range(args.steps):
        p.stepSimulation(physicsClientId=cid)
        if step % args.stride == 0:
            base_pos, _ = p.getBasePositionAndOrientation(rid, physicsClientId=cid)
            cam_target = [base_pos[0], base_pos[1], floor_z + target_frac]
            yaw = 20 + 70 * (step / max(args.steps - 1, 1))
            frames.append(capture_frame(
                cid, cam_target, args.width, args.height, yaw,
                distance=cam_distance, pitch=-18,
            ))

    final_pos, final_orn = p.getBasePositionAndOrientation(rid, physicsClientId=cid)
    euler = p.getEulerFromQuaternion(final_orn)
    print(f"최종 base_z={final_pos[2]:.3f} roll={np.degrees(euler[0]):.1f}deg "
          f"pitch={np.degrees(euler[1]):.1f}deg, 캡처 프레임 {len(frames)}개")

    diffs = [
        np.abs(frames[i].astype(int) - frames[0].astype(int)).sum()
        for i in range(1, len(frames))
    ]
    if not diffs or max(diffs) == 0:
        print("경고: 모든 프레임이 동일함 — 렌더가 멈췄을 가능성")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    imageio.mimsave(args.output, frames, fps=args.fps, loop=0)
    print(f"GIF 저장: {args.output} ({len(frames)} frames, {args.fps}fps)")

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
