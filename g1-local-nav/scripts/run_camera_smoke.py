"""Milestone 3 — camera pipeline smoke test (blueprint §17).

Captures 100 consecutive head-camera frames through G1Runtime, checks resolution/color order,
logs frame age, saves a sample JPEG, detects stale (non-updating) frames, and verifies the
camera publisher subprocess doesn't hang on shutdown.

Must run under `mjpython` (same macOS MuJoCo constraint as Milestones 1-2).

Usage:
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  mjpython scripts/run_camera_smoke.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "third_party" / "lerobot" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
from PIL import Image

from lerobot.cameras.zmq.configuration_zmq import ZMQCameraConfig
from g1_local_nav.robot_runtime import G1Runtime

N_FRAMES = 100
STALE_THRESHOLD_S = 0.5  # no new frame content for this long => flag as stale
OUT_DIR = Path(__file__).resolve().parent.parent / "runs" / "camera_smoke"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    camera_config = ZMQCameraConfig(
        server_address="localhost", port=5555, camera_name="head_camera",
        width=640, height=480, fps=30, warmup_s=5,
    )

    print(f"Connecting with camera (this opens the MuJoCo window; press 9 once to release")
    print(f"the elastic band, or ignore it — camera doesn't need the robot standing)...")

    frame_ages_ms: list[float] = []
    prev_rgb: np.ndarray | None = None
    last_change_t = time.monotonic()
    stale_events = 0
    shapes_seen: set[tuple] = set()

    connect_t0 = time.monotonic()
    with G1Runtime(camera_name="head_camera", cameras={"head_camera": camera_config}) as runtime:
        connect_s = time.monotonic() - connect_t0
        print(f"connect() took {connect_s:.1f}s")

        for i in range(N_FRAMES):
            frame = runtime.latest_frame()
            now_ns = time.time_ns()
            age_ms = (now_ns - frame.timestamp_ns) / 1e6
            frame_ages_ms.append(age_ms)
            shapes_seen.add(frame.rgb.shape)

            if prev_rgb is not None and np.array_equal(frame.rgb, prev_rgb):
                if time.monotonic() - last_change_t > STALE_THRESHOLD_S:
                    stale_events += 1
            else:
                last_change_t = time.monotonic()
            prev_rgb = frame.rgb

            if i == N_FRAMES // 2:
                sample_path = OUT_DIR / "sample_frame.jpg"
                Image.fromarray(frame.rgb).save(sample_path)
                print(f"saved sample frame to {sample_path} — check it visually: the target")
                print(f"ball should look RED, not cyan/blue (that would indicate BGR/RGB swap)")

            time.sleep(1 / 30)

        close_t0 = time.monotonic()
    close_s = time.monotonic() - close_t0

    ages = np.array(frame_ages_ms)
    print(f"\nframes received: {N_FRAMES}")
    print(f"shapes seen: {shapes_seen}")
    print(f"frame age (ms): mean={ages.mean():.1f} p50={np.median(ages):.1f} "
          f"p95={np.percentile(ages, 95):.1f} max={ages.max():.1f}")
    print(f"stale-frame events (no change for >{STALE_THRESHOLD_S}s): {stale_events}")
    print(f"close() took {close_s:.2f}s")
    if close_s > 5.0:
        print("WARNING: close() took a long time — publisher may not be shutting down cleanly")

    expected_shape = (480, 640, 3)
    if expected_shape not in shapes_seen:
        print(f"WARNING: expected shape {expected_shape} not seen — got {shapes_seen}")

    print("\nDone. Now check (outside this script):")
    print("  lsof -nP -iTCP:5555 -sTCP:LISTEN   # should show nothing")
    print("  ps aux | grep -i image_publish     # should show nothing")


if __name__ == "__main__":
    main()
