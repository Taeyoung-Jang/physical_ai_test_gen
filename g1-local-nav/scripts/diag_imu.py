"""Diagnostic: confirms the roll/pitch fix in robot_runtime.py (quaternion-derived, not the
sim bridge's broken imu.rpy.* field — see the comment in G1Runtime.latest_frame()).

Prints both the raw (broken) obs["imu.rpy.roll"] and G1Runtime's fixed RobotFrame.imu_roll side
by side. Expect: raw stays ~0.0, fixed actually changes as the robot moves/falls.

Usage:
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  mjpython scripts/diag_imu.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "third_party" / "lerobot" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from g1_local_nav.robot_runtime import G1Runtime


def main() -> None:
    runtime = G1Runtime(camera_name="head_camera", cameras={})
    print("Connecting (no camera, no viewer interaction needed — this just reads state)...")
    runtime.connect()

    time.sleep(2.0)  # let the lowstate subscriber thread receive at least one message

    for i in range(10):
        raw_obs = runtime._robot.get_observation()
        frame = runtime.latest_frame()
        print(
            f"[{i}] raw imu.rpy.roll={raw_obs.get('imu.rpy.roll')!r:>8}  "
            f"fixed roll={frame.imu_roll:+.4f} pitch={frame.imu_pitch:+.4f} yaw={frame.imu_yaw:+.4f}"
        )
        time.sleep(0.3)

    runtime.close()
    print("Done.")


if __name__ == "__main__":
    # Required on macOS: multiprocessing's default 'spawn' start method (used internally by
    # the image-publish subprocess) re-imports this file as __main__ in the child process.
    # Without this guard, module-level code re-runs there too — including runtime.connect(),
    # which then crashes because the spawned child isn't running under mjpython. This is
    # exactly the "RuntimeError: launch_passive requires mjpython" seen from a background
    # process while the real diagnostic loop above was still running fine.
    main()
