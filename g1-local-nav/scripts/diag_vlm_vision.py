"""Diagnostic: does the VLM actually condition on the image, or does it just emit a fixed
default token regardless of content? Triggered by a live run (ep_vlm_pickup_001) where the
model answered the exact literal string " FORWARD" on all 51/51 steps, including frames where
the red box had visibly drifted well left of center — where the prompt's own rules call for
TURN_LEFT. Bypasses the FastAPI server and the FORWARD/TURN/GRASP action prompt entirely: loads
VlmModel directly and asks a much simpler left/right/center question against three already-saved
frames from that run, to isolate "can it perceive box position at all" from "does it follow our
6-way decision rules."

No mjpython needed — pure image + model inference, no simulator involved.

Usage (g1-vlm venv):
  python scripts/diag_vlm_vision.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from services.vlm_server.model import VlmModel

RUN_DIR = Path(__file__).resolve().parent.parent / "runs" / "2026-08-15T232525Z_ep_vlm_pickup_001" / "frames"

FRAMES = [
    ("step_000_before.jpg", "box should read CENTER (box was dead-center, far away)"),
    ("step_025_before.jpg", "box should read CENTER or slightly LEFT (starting to drift)"),
    ("step_050_before.jpg", "box should read LEFT (clearly drifted left of center)"),
]

DIAG_PROMPT = (
    "Look at the red object in this image. Is it on the LEFT side, the RIGHT side, or the "
    "CENTER of the image? Answer with exactly one word: LEFT, RIGHT, or CENTER."
)


def main() -> None:
    model = VlmModel(max_tokens=8, temperature=0.0)
    print(f"Loading {model.model_id}...")
    model.load()
    print("Loaded.\n")

    for filename, expectation in FRAMES:
        path = RUN_DIR / filename
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        image = Image.open(path)
        raw_text, latency_ms = model.infer(image, DIAG_PROMPT)
        print(f"{filename}: model said {raw_text!r} ({latency_ms:.0f}ms) — expected: {expectation}")


if __name__ == "__main__":
    main()
