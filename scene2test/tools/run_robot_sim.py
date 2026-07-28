"""run_robot_sim.py — Stage 2: 3D scene 위에서 pick-and-place 케이스를 E2E 실행한다.

흐름: 입력 판별(Stage 1 sources.resolve_source) → SceneGraph 생성 → 지지면 선택
      → 로봇 배치 → target/obstacle/tray spawn → kinematic check + 6-margin
      oracle → 판정 출력 (+스냅샷/GIF)

사용:
  # 판정 + 스냅샷
  PYBULLET_MODE=DIRECT uv run python tools/run_robot_sim.py --source 00800

  # 지지면 선택 + 애니메이션 GIF
  PYBULLET_MODE=DIRECT uv run python tools/run_robot_sim.py \
      --source 00800 --surface 0 --gif

출력: reports/scene3d/<scene>_case.png, data/scene3d_anim/<scene>_case.gif
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
    parser = argparse.ArgumentParser(description="3D scene E2E pick-and-place 케이스")
    parser.add_argument(
        "--source", default="00800",
        help="HM3D scene id | mesh 파일 경로(.glb/.obj/.ply) | SceneGraph JSON 경로",
    )
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument(
        "--surface", type=int, default=-1,
        help="지지면 후보 인덱스. 기본 -1 = 배치 가능한 지지면 자동 선택",
    )
    parser.add_argument("--gif", action="store_true", help="pick-and-place GIF 생성")
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--report-dir", default="reports/scene3d")
    parser.add_argument("--anim-dir", default="data/scene3d_anim")
    return parser.parse_args()


def render_eye(cid, eye, target, width, height, far=40.0):
    view = p.computeViewMatrix(eye, target, [0, 0, 1], physicsClientId=cid)
    proj = p.computeProjectionMatrixFOV(
        fov=60, aspect=width / height, nearVal=0.05, farVal=far, physicsClientId=cid
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=cid,
    )
    return np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]


def workspace_camera(cid, ws, free_spots, floor_z):
    """작업공간을 바라보는 카메라 eye (LOS 확보 지점, 실패 시 대각 orbit)."""
    from scene3d.mesh_loader import pick_camera_eye

    target = [ws.target_pos[0], ws.target_pos[1], ws.surface.top_z + 0.15]
    eye = pick_camera_eye(
        cid, free_spots, target, floor_z, eye_height=ws.surface.top_z + 0.55,
        d_min=1.0, d_max=2.2,
    )
    if eye is None:
        base = np.array(ws.robot_base_pos)
        away = np.array(ws.target_pos[:2]) - base[:2]
        away = away / (np.linalg.norm(away) + 1e-9)
        eye = [
            float(base[0] - away[0] * 1.2),
            float(base[1] - away[1] * 1.2),
            ws.surface.top_z + 0.7,
        ]
    return eye, target


def main():
    args = parse_args()

    from physical_oracle import load_thresholds
    from scene3d.mesh_loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_static_scene,
        scene_extent_pybullet,
    )
    from scene3d.robot_workspace import run_case, setup_workspace
    from scene3d.sources import generate_scene_graph, resolve_source
    from sim_runner import load_robot_config

    try:
        source = resolve_source(args.source, split=args.split)
    except Exception as e:
        print(f"오류: 입력 판별/해석 실패 — {e}")
        sys.exit(1)

    # ── 씬 로드 ─────────────────────────────────────────────────────────
    t0 = time.time()
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_body_ids = load_static_scene(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    free_spots, floor_z = find_free_floor_spots(cid, lo, hi)
    print(f"[1/4] 씬 로드: {source.scene_id} ({time.time()-t0:.1f}s, "
          f"바닥 z={floor_z:.2f})")

    # ── SceneGraph 생성(Stage 1) + 작업공간 구성(Stage 2) ────────────────
    try:
        sg = generate_scene_graph(source, offset=converted.offset)
    except ValueError as e:
        print(f"오류: {e}")
        sys.exit(1)
    if not sg.support_surfaces:
        print("오류: 지지면 후보가 없습니다.")
        sys.exit(1)
    if args.surface >= len(sg.support_surfaces):
        print(f"오류: --surface {args.surface} 범위 밖 "
              f"(후보 {len(sg.support_surfaces)}개)")
        sys.exit(1)

    robot_cfg = load_robot_config("config/robot_config.yaml")
    candidates = (
        sg.support_surfaces if args.surface < 0 else [sg.support_surfaces[args.surface]]
    )
    ws = None
    for surf in candidates:
        area = (surf.bounds["x"][1] - surf.bounds["x"][0]) * \
               (surf.bounds["y"][1] - surf.bounds["y"][0])
        print(f"[2/4] 지지면 시도: {surf.id} "
              f"(높이 {surf.height:.2f}m, 면적 {area:.2f}m²)")
        try:
            ws = setup_workspace(
                converted, scene_body_ids, sg, surf.id, floor_z, robot_cfg, cid,
            )
            break
        except RuntimeError as e:
            print(f"      배치 실패: {e}")
    if ws is None:
        print("오류: 모든 지지면 후보에서 로봇 배치 실패")
        sys.exit(1)
    print(f"      로봇 베이스: {np.round(ws.robot_base_pos, 2).tolist()}, "
          f"주변 obstacle proxy {len(ws.obstacle_proxies)}개")
    print(f"      target: {np.round(ws.target_pos, 2).tolist()}, "
          f"tray: {np.round(ws.destination_pos, 2).tolist()}")

    # ── oracle ──────────────────────────────────────────────────────────
    t0 = time.time()
    thresholds = load_thresholds("config/thresholds.yaml")
    oracle, kin = run_case(ws, thresholds)
    print(f"[3/4] Oracle ({time.time()-t0:.1f}s): "
          f"verdict={oracle.verdict} robustness={oracle.robustness*100:.1f}cm "
          f"binding={oracle.binding_margin}")
    for name, v in oracle.margins.items():
        print(f"        {name:12s} {v*100:+8.2f} cm")
    if oracle.reason:
        print(f"        reason: {oracle.reason}")

    # ── 스냅샷 + GIF ────────────────────────────────────────────────────
    from PIL import Image

    import sim_runner

    eye, cam_target = workspace_camera(cid, ws, free_spots, floor_z)
    os.makedirs(args.report_dir, exist_ok=True)

    # home 자세로 되돌린 후 스냅샷
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]
    sim_runner.set_joint_state(home_q, ws.robot_cfg)
    snap = render_eye(cid, eye, cam_target, args.width, args.height)
    snap_path = os.path.join(args.report_dir, f"{source.scene_id}_case.png")
    Image.fromarray(snap).save(snap_path)
    print(f"[4/4] 스냅샷: {snap_path}")

    if args.gif:
        frames = animate_pick_place(cid, ws, eye, cam_target, args)
        if frames:
            import imageio
            os.makedirs(args.anim_dir, exist_ok=True)
            gif_path = os.path.join(args.anim_dir, f"{source.scene_id}_case.gif")
            imageio.mimsave(gif_path, frames, duration=0.08, loop=0)
            # 프레임이 실제로 변하는지 검증
            diffs = [
                float(np.abs(frames[i].astype(int) - frames[0].astype(int)).mean())
                for i in range(1, len(frames), max(1, len(frames) // 5))
            ]
            print(f"      GIF: {gif_path} ({len(frames)} frames, "
                  f"mean|Δ|={np.mean(diffs):.1f})")

    p.disconnect(physicsClientId=cid)


def animate_pick_place(cid, ws, eye, cam_target, args) -> list[np.ndarray]:
    """kinematic pick-and-place 재생 (grasp 후 target을 그리퍼에 표시용 부착)."""
    import sim_runner

    cfg = ws.robot_cfg
    n = cfg["motion"]["path_samples_per_segment"]
    grasp_orn = list(p.getQuaternionFromEuler([0, math.pi, 0]))
    tpos = ws.target_pos
    dpos = ws.destination_pos
    pre = cfg["motion"]["pre_offset"]
    lift = cfg["motion"]["lift_height"]

    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]
    waypoints = [
        ("pre_grasp", [tpos[0], tpos[1], tpos[2] + pre]),
        ("grasp", tpos),
        ("lift", [tpos[0], tpos[1], tpos[2] + lift]),
        ("pre_place", [dpos[0], dpos[1], dpos[2] + pre]),
        ("place", [dpos[0], dpos[1], dpos[2] + 0.03]),
    ]

    qs = [home_q]
    ok = True
    for name, pos in waypoints:
        q = sim_runner.solve_ik(pos, grasp_orn, cfg)
        if q is None:
            print(f"      GIF: {name} IK 실패 — 애니메이션 생략")
            ok = False
            break
        qs.append(q)
    if not ok:
        return []

    target_body = ws.body_map["target_block"]
    ee_link = cfg["robot"]["ee_link_index"]
    frames = []
    carrying = False
    for seg_idx in range(len(qs) - 1):
        path = sim_runner.interpolate_joint_path(qs[seg_idx], qs[seg_idx + 1], n)
        for q in path:
            sim_runner.set_joint_state(q, cfg)
            if seg_idx >= 2:  # grasp 완료 후 → 운반 표시
                carrying = True
            if carrying:
                ee = p.getLinkState(
                    ws.robot_body_id, ee_link, physicsClientId=cid
                )[4]
                p.resetBasePositionAndOrientation(
                    target_body,
                    [ee[0], ee[1], ee[2] - 0.03],
                    [0, 0, 0, 1],
                    physicsClientId=cid,
                )
            frames.append(
                render_eye(cid, eye, cam_target, args.width, args.height)
            )
    return frames


if __name__ == "__main__":
    main()
