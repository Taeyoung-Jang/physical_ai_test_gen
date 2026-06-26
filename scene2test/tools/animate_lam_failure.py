"""tools/animate_lam_failure.py — LAM-Guided counterexample 애니메이션 GIF.

LAM-Guided 루프가 발견한 counterexample 을 시각화한다. 핵심 스토리:
  "instruction은 빨간 캔(target)을 집으라 했는데, 정책이 옆의 유사 distractor를 집었다"
또는 "target을 향하다 삽입된 blocker/human과 충돌/근접했다".

로봇은 정책이 실제로 고른 객체(selected_obj_id)를 향해 움직이며, 삽입된 asset 은
semantic 색으로 다시 칠해(red distractor → 빨강) 데모가 직관적이게 한다.

macOS에서 깨지는 OpenGL 대신 ER_TINY_RENDERER 로 캡처(검증된 방식).

사용 예:
  # 최신 LAM 로그의 counterexample들을 애니메이션
  PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --max 4

  # 특정 로그 / family 필터
  PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py \
      --log data/lam_guided_logs/lam_scene_00001_xxx.json \
      --family semantic_distractor --max 3
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import imageio
import numpy as np
import PIL.Image
import PIL.ImageDraw
import pybullet as p

import scene_builder
import sim_runner
from scene_builder import load_scene, reset_simulation
from scene_graph import Role, SceneGraph
from sim_runner import (
    load_robot, load_robot_config, solve_ik,
    interpolate_joint_path, set_joint_state, get_robot_id,
)
from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.case_apply import insert_assets

OPEN, CLOSED = 0.04, 0.005

_COLOR_RGBA = {
    "red":    [0.85, 0.15, 0.15, 1.0],
    "blue":   [0.15, 0.35, 0.85, 1.0],
    "green":  [0.15, 0.75, 0.25, 1.0],
    "grey":   [0.60, 0.60, 0.60, 1.0],
    "orange": [0.95, 0.65, 0.10, 0.55],
}
_COLOR_WORDS = ("red", "blue", "green", "orange")


def parse_args():
    ap = argparse.ArgumentParser(description="LAM-Guided counterexample 애니메이션")
    ap.add_argument("--log", help="LAM 로그 JSON (기본: 최신 lam_*.json)")
    ap.add_argument("--family", help="이 family만 (semantic_distractor 등)")
    ap.add_argument("--failure", help="이 failure type 포함 케이스만 (예: wrong_object_grounding)")
    ap.add_argument("--max", type=int, default=4)
    ap.add_argument("--output-dir", default="data/lam_anim")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--samples", type=int, default=14, help="구간당 waypoint 수")
    ap.add_argument("--fps", type=int, default=20)
    return ap.parse_args()


def _latest_log() -> str | None:
    logs = sorted(glob.glob("data/lam_guided_logs/lam_*.json"))
    return logs[-1] if logs else None


def _semantic_color(obj) -> list[float] | None:
    """객체의 semantic_tags / color 로부터 렌더 색을 고른다(없으면 None=역할색 유지)."""
    if obj.role == Role.HUMAN_ZONE:
        return _COLOR_RGBA["orange"]
    tags = [t.lower() for t in obj.extra.get("semantic_tags", [])]
    for w in _COLOR_WORDS:
        if w in tags:
            return _COLOR_RGBA[w]
    col = obj.extra.get("color")
    return _COLOR_RGBA.get(col)


def _project(pos3d, view, proj, width, height):
    """월드 좌표 → 화면 픽셀 (view/proj 는 column-major 16-list)."""
    v = np.array(view, dtype=float).reshape(4, 4).T
    pr = np.array(proj, dtype=float).reshape(4, 4).T
    clip = pr @ v @ np.array([pos3d[0], pos3d[1], pos3d[2], 1.0])
    if abs(clip[3]) < 1e-9:
        return None
    ndc = clip[:3] / clip[3]
    if ndc[2] < -1 or ndc[2] > 1:
        return None
    sx = int((ndc[0] * 0.5 + 0.5) * width)
    sy = int((1.0 - (ndc[1] * 0.5 + 0.5)) * height)
    return sx, sy


def capture_frame(cid, width, height, yaw, cam_target, markers=None):
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=cam_target, distance=1.5, yaw=yaw, pitch=-38,
        roll=0, upAxisIndex=2, physicsClientId=cid)
    proj = p.computeProjectionMatrixFOV(
        fov=60, aspect=width / height, nearVal=0.01, farVal=10.0, physicsClientId=cid)
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=cid)
    frame = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    if markers:
        img = PIL.Image.fromarray(frame)
        d = PIL.ImageDraw.Draw(img)
        for pos3d, label, color in markers:
            sp = _project(pos3d, view, proj, width, height)
            if sp is None:
                continue
            x, y = sp
            r = 14
            d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=3)
            d.text((x - r, y - r - 12), label, fill=color)
        frame = np.array(img)
    return frame


def set_gripper(width, robot_cfg, cid):
    rid = get_robot_id()
    for idx in robot_cfg["robot"]["finger_joint_indices"]:
        p.resetJointState(rid, idx, width, physicsClientId=cid)


def _caption(frame: np.ndarray, lines: list[tuple[str, tuple]]) -> np.ndarray:
    img = PIL.Image.fromarray(frame)
    d = PIL.ImageDraw.Draw(img)
    y = 6
    for text, color in lines:
        d.text((8, y), text, fill=color)
        y += 13
    return np.array(img)


def reconstruct_scene(scene_id: str, rec: dict, bank: GeneratedAssetBank) -> SceneGraph:
    base = annotate_scene_semantics(SceneGraph.load(f"data/scene_library/{scene_id}.json"))
    sg = insert_assets(base, rec["insert_specs"], bank)
    return annotate_scene_semantics(sg)


def build_lam_animation(sg: SceneGraph, selected_id: str, cid, robot_cfg,
                        width, height, samples, caption_lines):
    reset_simulation()
    body_map = load_scene(sg)
    load_robot(robot_cfg)

    # 삽입 asset 을 semantic 색으로 다시 칠한다 (red distractor → 빨강)
    for obj in sg.objects:
        if obj.id not in body_map or obj.role == Role.HUMAN_ZONE:
            continue
        col = _semantic_color(obj)
        if col:
            p.changeVisualShape(body_map[obj.id], -1, rgbaColor=col, physicsClientId=cid)

    selected = sg.get_object(selected_id) or sg.target()
    dest = sg.destination()
    if selected is None:
        return None, "selected 객체 없음"

    lift_h = robot_cfg["motion"]["lift_height"]
    pre_off = robot_cfg["motion"]["pre_offset"]
    down = list(p.getQuaternionFromEuler([0, math.pi, 0], physicsClientId=cid))
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]

    sp = list(selected.position)
    grasp_q = solve_ik(sp, down, robot_cfg)
    if grasp_q is None:
        return None, "IK 실패 (선택 객체 도달 불가)"
    pre_q = solve_ik([sp[0], sp[1], sp[2] + pre_off], down, robot_cfg) or home_q
    lift_q = solve_ik([sp[0], sp[1], sp[2] + lift_h], down, robot_cfg) or grasp_q

    goals = [(pre_q, OPEN), (grasp_q, OPEN), (grasp_q, CLOSED), (lift_q, CLOSED)]
    if dest is not None:
        dp = list(dest.position)
        preplace_q = solve_ik([dp[0], dp[1], dp[2] + pre_off + lift_h], down, robot_cfg)
        place_q = solve_ik([dp[0], dp[1], dp[2] + pre_off], down, robot_cfg)
        if preplace_q and place_q:
            goals += [(preplace_q, CLOSED), (place_q, CLOSED),
                      (place_q, OPEN), (home_q, OPEN)]
        else:
            goals += [(home_q, CLOSED)]
    else:
        goals += [(home_q, CLOSED)]
    set_joint_state(home_q, robot_cfg)

    sel_body = body_map.get(selected.id)
    ee_link = robot_cfg["robot"]["ee_link_index"]
    rid = get_robot_id()
    cam_target = [sp[0], sp[1] - 0.05, 0.12]
    grasp_z_off = 0.045

    target = sg.target()
    wrong = target is not None and selected.id != target.id
    # 마커: TARGET(초록, 고정) + PICKED/REACHED(빨강, 그리퍼 따라감)
    target_pos = list(target.position) if target is not None else None

    frames = []
    total = len(goals) * samples
    step = 0
    prev_q = home_q
    for q_goal, grip in goals:
        carrying = grip == CLOSED
        for q in interpolate_joint_path(prev_q, q_goal, samples):
            set_joint_state(q, robot_cfg)
            set_gripper(grip, robot_cfg, cid)
            p.stepSimulation(physicsClientId=cid)
            if carrying and sel_body is not None:
                ee = p.getLinkState(rid, ee_link, physicsClientId=cid)[4]
                p.resetBasePositionAndOrientation(
                    sel_body, [ee[0], ee[1], ee[2] - grasp_z_off],
                    [0, 0, 0, 1], physicsClientId=cid)
            markers = []
            if wrong and target_pos is not None:
                sel_now = p.getBasePositionAndOrientation(sel_body, physicsClientId=cid)[0] \
                    if sel_body is not None else selected.position
                markers.append((target_pos, "TARGET", (60, 230, 90)))
                markers.append((list(sel_now), "PICKED", (255, 70, 70)))
            yaw = 35 + 40 * (step / max(total - 1, 1))
            fr = capture_frame(cid, width, height, yaw, cam_target, markers)
            frames.append(_caption(fr, caption_lines))
            step += 1
        prev_q = q_goal
    return frames, None


def main():
    args = parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    log_path = args.log or _latest_log()
    if not log_path or not os.path.exists(log_path):
        print("❌ LAM 로그를 찾을 수 없습니다 (먼저 lam_guided_loop 실행)")
        return
    with open(log_path, encoding="utf-8") as f:
        log = json.load(f)
    scene_id = log["scene_id"]
    ces = log.get("counterexamples", [])
    if args.family:
        ces = [c for c in ces if c["family"] == args.family]
    if args.failure:
        ces = [c for c in ces if args.failure in c.get("failure_types", [])]
    # 다양성: family별로 분산해서 고르기
    seen, picked = set(), []
    for c in ces:
        key = c["family"]
        if key not in seen:
            picked.append(c); seen.add(key)
    picked += [c for c in ces if c not in picked]
    ces = picked[: args.max]
    if not ces:
        print("❌ 일치하는 counterexample 없음")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    robot_cfg = load_robot_config("config/robot_config.yaml")
    bank = GeneratedAssetBank.default("data/generated_assets/index.json")

    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid
    sim_runner._ROBOT_BODY_ID = None

    print(f"\n🎬 LAM counterexample 애니메이션  (log={os.path.basename(log_path)})\n")
    try:
        for i, rec in enumerate(ces, 1):
            cid_name = rec["case_id"]
            fam = rec["family"]
            fts = rec.get("failure_types", [])
            sel, exp = rec.get("selected_obj_id", ""), rec.get("expected_obj_id", "")
            print(f"[{i}/{len(ces)}] {cid_name} [{rec['verdict']}] {fam} → {fts}")

            wrong = sel != exp and exp
            cap = [
                (f"family: {fam}", (255, 230, 120)),
                (f"{rec['verdict']}: {','.join(fts)[:42]}", (255, 110, 110)),
                (f"instruction: {rec.get('instruction','')[:34]}", (220, 220, 220)),
                ((f"-> reached {sel} (NOT {exp})" if wrong
                  else f"-> reached {sel}; obstacle/human in path"),
                 (255, 180, 90) if wrong else (140, 200, 255)),
            ]
            scene = reconstruct_scene(scene_id, rec, bank)
            frames, err = build_lam_animation(
                scene, sel, cid, robot_cfg, args.width, args.height,
                args.samples, cap)
            if err:
                print(f"    ⚠️ {err}\n"); continue
            uniq = len({fr.tobytes() for fr in frames})
            if uniq <= 1:
                print(f"    ❌ 모든 프레임 동일 (렌더 실패) — 저장 안 함\n"); continue
            out = os.path.join(args.output_dir, f"{cid_name}_{fam}.gif")
            imageio.mimsave(out, frames, fps=args.fps, loop=0)
            print(f"    ✓ {len(frames)}프레임, {uniq}개 고유 → {out}\n")
    finally:
        p.disconnect(physicsClientId=cid)
    print("✓ 완료")


if __name__ == "__main__":
    main()
