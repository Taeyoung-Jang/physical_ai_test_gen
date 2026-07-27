"""load_hm3d_scene.py — HM3D 실제 스캔 씬을 PyBullet에 로드하고 스냅샷을 찍는다.

사용:
  # 씬 목록 (semantic annotation 보유 여부 포함)
  uv run python tools/load_hm3d_scene.py --list

  # 씬 추출 + 변환 + 로드 + 4-뷰 스냅샷
  PYBULLET_MODE=DIRECT uv run python tools/load_hm3d_scene.py --scene 00800

  # 로봇 포함, 위치 지정
  PYBULLET_MODE=DIRECT uv run python tools/load_hm3d_scene.py \
      --scene 00800 --robot --robot-pos 1.0 0.5

출력: reports/hm3d/<scene_dir>_views.png (+ 개별 뷰 PNG)
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="HM3D 씬 PyBullet 로더 + 스냅샷")
    parser.add_argument("--list", action="store_true", help="씬 목록 출력")
    parser.add_argument("--scene", default="00800", help="씬 참조 (id/해시/디렉터리명 접두)")
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--dataset-dir", default=None, help="HM3D tar 디렉터리")
    parser.add_argument(
        "--no-collision", action="store_true", help="collision shape 생략 (렌더 전용, 빠름)"
    )
    parser.add_argument("--robot", action="store_true", help="Franka 로봇 배치")
    parser.add_argument(
        "--robot-pos", nargs=2, type=float, default=None, metavar=("X", "Y"),
        help="로봇 위치 (생략 시 raycast로 빈 바닥 자동 탐색)",
    )
    parser.add_argument("--force-convert", action="store_true", help="OBJ 캐시 재생성")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out-dir", default="reports/hm3d")
    return parser.parse_args()


def _render(cid: int, view, width: int, height: int, far: float) -> np.ndarray:
    proj = p.computeProjectionMatrixFOV(
        fov=60, aspect=width / height, nearVal=0.05, farVal=far, physicsClientId=cid
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height,
        viewMatrix=view,
        projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER,
        physicsClientId=cid,
    )
    arr = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)
    return arr[:, :, :3]


def capture(
    cid: int,
    target: list[float],
    distance: float,
    yaw: float,
    pitch: float,
    width: int,
    height: int,
    far: float = 60.0,
) -> np.ndarray:
    """orbit 카메라 (전경/탑뷰용)."""
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=target,
        distance=distance,
        yaw=yaw,
        pitch=pitch,
        roll=0,
        upAxisIndex=2,
        physicsClientId=cid,
    )
    return _render(cid, view, width, height, far)


def capture_from_eye(
    cid: int,
    eye: list[float],
    target: list[float],
    width: int,
    height: int,
    far: float = 60.0,
) -> np.ndarray:
    """eye 위치 지정 카메라 (실내용 — 벽 관통 방지)."""
    view = p.computeViewMatrix(
        cameraEyePosition=eye,
        cameraTargetPosition=target,
        cameraUpVector=[0, 0, 1],
        physicsClientId=cid,
    )
    return _render(cid, view, width, height, far)


def main():
    args = parse_args()

    from hm3d.dataset import HM3DDataset
    from hm3d.loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_hm3d_static,
        pick_camera_eye,
        scene_extent_pybullet,
    )

    ds = HM3DDataset(split=args.split, **(
        {"dataset_dir": args.dataset_dir} if args.dataset_dir else {}
    ))

    if args.list:
        scenes = ds.list_scenes()
        print(f"[{args.split}] {len(scenes)}개 씬:")
        for e in scenes:
            sem = "semantic O" if e.has_semantic else "semantic x"
            print(f"  {e.scene_dir}  [{sem}]")
        return

    # ── 1. 추출 ─────────────────────────────────────────────────────────
    t0 = time.time()
    extracted = ds.extract(args.scene)
    entry = extracted.entry
    print(f"[1/4] 추출 완료: {entry.scene_dir} ({time.time()-t0:.1f}s)")
    print(f"      glb: {extracted.glb_path}")
    if extracted.semantic_txt_path:
        print(f"      semantic: {extracted.semantic_txt_path.name} 있음")

    # ── 2. 변환 (캐시) ──────────────────────────────────────────────────
    t0 = time.time()
    converted = convert_glb_to_obj(
        extracted.glb_path, entry.scene_dir, force=args.force_convert
    )
    lo, hi = scene_extent_pybullet(converted)
    print(f"[2/4] OBJ 변환/캐시: {len(converted.chunk_objs)} chunks, "
          f"{converted.n_faces:,} faces ({time.time()-t0:.1f}s)")
    print(f"      bounds(PyBullet): {np.round(lo, 2)} ~ {np.round(hi, 2)}")

    # ── 3. PyBullet 로드 ────────────────────────────────────────────────
    t0 = time.time()
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)

    body_ids = load_hm3d_static(converted, cid, collision=not args.no_collision)
    print(f"[3/4] PyBullet 로드: {len(body_ids)} static bodies ({time.time()-t0:.1f}s)")

    lo, hi = scene_extent_pybullet(converted)

    # 빈 바닥 탐색 (로봇 배치 + interior 카메라 타깃)
    free_spots: list[tuple[float, float]] = []
    floor_z = 0.0
    if not args.no_collision:
        free_spots, floor_z = find_free_floor_spots(cid, lo, hi)
        print(f"      빈 바닥 지점: {len(free_spots)}개 (바닥 z={floor_z:.3f})")

    robot_pos = None
    if args.robot:
        if args.robot_pos is not None:
            robot_pos = [args.robot_pos[0], args.robot_pos[1], floor_z]
        elif free_spots:
            robot_pos = [free_spots[0][0], free_spots[0][1], floor_z]
        else:
            robot_pos = [0.0, 0.0, 0.0]
        robot_id = p.loadURDF(
            "franka_panda/panda.urdf",
            basePosition=robot_pos,
            useFixedBase=True,
            physicsClientId=cid,
        )
        home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]
        for i, q in enumerate(home_q):
            p.resetJointState(robot_id, i, q, physicsClientId=cid)
        print(f"      로봇 배치: {np.round(robot_pos, 2).tolist()}")

    # ── 4. 스냅샷 ───────────────────────────────────────────────────────
    t0 = time.time()
    extent = hi - lo
    d_max = float(max(extent[0], extent[1]))

    far = d_max * 3
    os.makedirs(args.out_dir, exist_ok=True)
    frames = {}

    # 전경 뷰 (orbit — 벽 밖에서 봐도 dollhouse로 잘 보임)
    frames["top"] = capture(
        cid, target=[0, 0, 0], distance=d_max * 0.85, yaw=0, pitch=-89.5,
        width=args.width, height=args.height, far=far,
    )
    frames["persp"] = capture(
        cid, target=[0, 0, float(extent[2]) * 0.25], distance=d_max * 0.85,
        yaw=45, pitch=-40, width=args.width, height=args.height, far=far,
    )

    # 실내 뷰 — 시야가 확보된 빈 바닥 지점에서 촬영 (벽 관통 방지)
    if robot_pos is not None:
        interior_target = [robot_pos[0], robot_pos[1], robot_pos[2] + 0.5]
    elif free_spots:
        interior_target = [free_spots[0][0], free_spots[0][1], floor_z + 1.0]
    else:
        interior_target = [0.0, 0.0, 1.0]

    eye = pick_camera_eye(cid, free_spots, interior_target, floor_z) if free_spots else None
    if eye is not None:
        frames["interior"] = capture_from_eye(
            cid, eye, interior_target, width=args.width, height=args.height, far=far
        )
        print(f"      interior 카메라: eye={np.round(eye, 2).tolist()}")
    else:
        print("      interior 카메라: 시야 확보 지점 없음 → 생략")

    if robot_pos is not None and free_spots:
        eye_r = pick_camera_eye(
            cid, free_spots, interior_target, floor_z, d_min=0.9, d_max=2.0, eye_height=1.1
        )
        if eye_r is not None:
            frames["robot"] = capture_from_eye(
                cid, eye_r, interior_target, width=args.width, height=args.height, far=far
            )

    from PIL import Image, ImageDraw

    n = len(frames)
    cols = 2
    rows = (n + cols - 1) // cols
    grid = Image.new("RGB", (args.width * cols, args.height * rows), (20, 20, 20))
    for i, (name, frame) in enumerate(frames.items()):
        img = Image.fromarray(frame)
        ImageDraw.Draw(img).text((12, 10), f"{entry.scene_dir} — {name}", fill=(255, 220, 0))
        grid.paste(img, ((i % cols) * args.width, (i // cols) * args.height))
        img.save(os.path.join(args.out_dir, f"{entry.scene_dir}_{name}.png"))

    grid_path = os.path.join(args.out_dir, f"{entry.scene_dir}_views.png")
    grid.save(grid_path)
    print(f"[4/4] 스냅샷 {n}개 저장 ({time.time()-t0:.1f}s): {grid_path}")

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
