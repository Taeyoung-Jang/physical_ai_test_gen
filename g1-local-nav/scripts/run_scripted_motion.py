"""Milestone 2 acceptance test — scripted locomotion through G1Runtime + ActionMapper
(blueprint §17, Milestone 2). No gamepad or keyboard teleop involved; see
src/g1_local_nav/robot_runtime.py for why the teleop CLI can't move G1 at all.

Sequence (blueprint §17): STOP 2s -> FORWARD 1s -> STOP 1s -> TURN_LEFT 0.5s -> STOP 1s ->
TURN_RIGHT 0.5s -> STOP.

Must run under `mjpython`, not plain `python` (macOS MuJoCo GUI constraint). The scene's
elastic band starts enabled — click the MuJoCo window and press "9" to release it once it opens.

Usage:
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  mjpython scripts/run_scripted_motion.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "third_party" / "lerobot" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from g1_local_nav.action import NavAction
from g1_local_nav.action_mapper import ActionMapper
from g1_local_nav.robot_runtime import G1Runtime

SEQUENCE: list[tuple[NavAction, float]] = [
    (NavAction.STOP, 2.0),
    (NavAction.FORWARD, 5.0),  # was 1.0s — too short for the gait to ramp up and cover
                               # visible distance (blueprint §17's 1s figure is a starting
                               # point, not a floor; empirically widened after first test
                               # showed near-zero displacement despite stable standing)
    (NavAction.STOP, 1.0),
    (NavAction.TURN_LEFT, 2.0),  # was 0.5s, same reasoning
    (NavAction.STOP, 1.0),
    (NavAction.TURN_RIGHT, 2.0),
    (NavAction.STOP, 2.0),
]


def main() -> None:
    mapper = ActionMapper()

    print("Connecting (MuJoCo window will open — click it and press 9 to release the elastic")
    print("band, then this script waits 8s before starting the scripted sequence)...")

    with G1Runtime() as runtime:
        time.sleep(8.0)

        for action, seconds in SEQUENCE:
            print(f"-> {action.value} for {seconds}s")
            command = mapper.to_remote(action)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                runtime.send_remote(command)
                time.sleep(0.02)  # 50 Hz, matches controller cadence

    print("Disconnected cleanly.")


if __name__ == "__main__":
    main()
