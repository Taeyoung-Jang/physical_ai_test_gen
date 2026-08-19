"""Standalone diagnostic for the pick-and-carry extension (beyond blueprint §14's navigate-and-
stop scope): proves the weld-based kinematic grasp works end-to-end against the REAL simulator —
walk to the pedestal, reach, grasp, carry to a new spot, release — logging the target object's
and the robot's ground-truth trajectory to runs/pickup_smoke/ so it can be inspected without a
GUI (same pattern as scripts/run_camera_smoke.py, scripts/diag_imu.py).

Must run under mjpython (see envs/SETUP_NOTES.md) with G1_LOCAL_NAV_SCENE=1 set — the plain
upstream scene has no pedestal/box/weld constraint at all, so this is a no-op there.

Usage:
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  export G1_LOCAL_NAV_SCENE=1
  mjpython scripts/run_pickup_smoke.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from g1_local_nav.action import NavAction
from g1_local_nav.action_mapper import ActionMapper
from g1_local_nav.robot_runtime import GRASP_REACH_POSE as REACH_POSE
from g1_local_nav.robot_runtime import GRASP_REST_POSE as REST_POSE
from g1_local_nav.robot_runtime import G1Runtime

TARGET_XY = (2.0, 0.0)  # must match configs/app.yaml task.target_x/target_y
OUT_DIR = Path(__file__).resolve().parent.parent / "runs" / "pickup_smoke"


def ramp_arm(runtime: G1Runtime, from_pose: dict, to_pose: dict, steps: int = 15, step_dt: float = 0.1) -> None:
    """Moves the arm through `steps` intermediate joint-angle waypoints instead of jumping
    straight to `to_pose` in one command. A one-shot jump lets the PD controller drive the
    forearm through whatever's in between as fast as it can — this is exactly what knocked the
    pickup target off its pedestal on the first live run (box height crashed from 0.85m to
    0.21m in the same window the arm reached, see conversation record): the arm swept through
    the object's resting position on its way to the target angles. Ramping doesn't add
    collision *avoidance* (still no path planning), but the much slower, smaller per-step
    motion gives contacts far less momentum to impart if the arm does graze something.
    """
    for i in range(1, steps + 1):
        frac = i / steps
        pose = {k: from_pose[k] + frac * (to_pose[k] - from_pose[k]) for k in to_pose}
        runtime.send_arm_action(pose)
        time.sleep(step_dt)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []

    runtime = G1Runtime(camera_name="head_camera")
    mapper = ActionMapper()

    def record(tag: str) -> None:
        entry = {
            "t": round(time.monotonic(), 2),
            "tag": tag,
            "box_xyz": runtime.object_xyz(),
            "pelvis_xyz": runtime.object_xyz("pelvis"),
            "wrist_xyz": runtime.object_xyz("right_wrist_yaw_link"),
            "grasping": runtime.is_grasping(),
        }
        log.append(entry)
        print(entry)

    print("Connecting (this opens the MuJoCo window)...")
    with runtime:
        released = runtime.release_elastic_band()
        print(f"elastic band auto-release: {'done' if released else 'NOT applied — sim internals unreachable'}")
        record("start")

        print("Walking forward toward the pedestal...")
        forward_cmd = mapper.to_remote(NavAction.FORWARD)
        # 0.65m (pelvis-to-target), not closer — the first live run's own walk (stopping at
        # 0.5m) already bumped the pedestal and shifted the box before the arm ever moved (box
        # xy drifted from (2.0, 0) to (2.11, 0.03) during this phase alone, see conversation
        # record). Backing off here and leaning on the gentler nudge loop below to close the
        # rest of the gap in small, checked increments instead.
        walk_start = time.monotonic()
        while time.monotonic() - walk_start < 30.0:
            pelvis = runtime.object_xyz("pelvis")
            if pelvis is not None:
                dx, dy = pelvis[0] - TARGET_XY[0], pelvis[1] - TARGET_XY[1]
                if (dx * dx + dy * dy) ** 0.5 < 0.65:
                    break
            runtime.send_remote(forward_cmd)
            time.sleep(0.05)
        runtime.stop()
        time.sleep(0.5)
        record("after_walk_forward")

        print("Extending arm to the reach pose (ramped, not a single jump)...")
        ramp_arm(runtime, REST_POSE, REACH_POSE)
        time.sleep(0.5)
        record("after_reach")

        print("Attempting grasp (with small forward nudges if still out of reach)...")
        grasp_radius_m = 0.5
        pedestal_top_z = 0.85  # see the pedestal's own comment in scene_43dof_with_target.xml
        grasped = runtime.try_grasp(max_distance_m=grasp_radius_m)
        nudges = 0
        while not grasped and nudges < 12:
            wrist = runtime.object_xyz("right_wrist_yaw_link")
            box = runtime.object_xyz()
            if box is not None and box[2] < pedestal_top_z - 0.2:
                # Happened on the first live run: the arm's one-shot jump to REACH_POSE swept
                # through the box and knocked it clean off the pedestal before any grasp attempt
                # (see conversation record) — no point burning the rest of the nudge budget
                # walking toward a box that's already on the floor several nudges away.
                print(f"  box appears to have fallen off the pedestal (z={box[2]:.3f}) — stopping nudges early")
                break
            print(f"  nudge {nudges}: wrist={wrist} box={box} — still out of range, stepping forward")
            # Retract before walking, re-extend once stopped — an extended arm badly
            # destabilizes straight-line walking. Live run: pelvis drifted sideways at
            # ~-0.109 m/s while walking with the arm extended vs ~-0.0145 m/s with it at rest
            # (~7.5x faster, see conversation record) — the whole-body balance controller
            # visibly overcompensates for the extended arm's asymmetric load. Walking with the
            # arm neutral avoids that; we only need it extended to actually test the grasp.
            ramp_arm(runtime, REACH_POSE, REST_POSE, steps=8, step_dt=0.05)
            for _ in range(10):
                runtime.send_remote(forward_cmd)
                time.sleep(0.05)
            runtime.stop()
            time.sleep(0.3)
            ramp_arm(runtime, REST_POSE, REACH_POSE, steps=8, step_dt=0.05)
            time.sleep(0.3)
            grasped = runtime.try_grasp(max_distance_m=grasp_radius_m)
            nudges += 1
        print(f"grasp result: {grasped} (after {nudges} nudge(s))")
        record("after_grasp_attempt")

        if grasped:
            print("Turning and walking to a new spot while carrying...")
            turn_cmd = mapper.to_remote(NavAction.TURN_LEFT)
            for _ in range(30):
                runtime.send_remote(turn_cmd)
                time.sleep(0.05)
            for _ in range(60):
                runtime.send_remote(forward_cmd)
                time.sleep(0.05)
            runtime.stop()
            time.sleep(0.5)
            record("after_carry")

            print("Releasing...")
            runtime.release_grasp()
            ramp_arm(runtime, REACH_POSE, REST_POSE)
            time.sleep(0.5)
            record("after_release")
        else:
            print("Grasp failed — skipping carry/release. See after_grasp_attempt distance in the log.")

    out_path = OUT_DIR / f"pickup_smoke_{int(time.time())}.json"
    out_path.write_text(json.dumps(log, indent=2))
    print(f"saved log to {out_path}")


if __name__ == "__main__":
    main()
