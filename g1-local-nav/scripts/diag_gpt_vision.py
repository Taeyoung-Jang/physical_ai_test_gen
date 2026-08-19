"""Diagnostic: does GPT-5 (via OpenAI API) correctly ground color/position in an image, where
the local SmolVLM2-500M-Video-Instruct-mlx checkpoint did not (100% wrong on trivially easy
synthetic red/blue/green squares and left/center/right positions — see conversation record)?
Same test images, same style of question, swapped model/backend only.

No mjpython, no simulator — pure API calls against saved/synthetic image files. Reads
OPENAI_API_KEY and OPENAI_MODEL from .env in the repo root (never printed).

Usage (any venv with httpx — g1-sim has it):
  python scripts/diag_gpt_vision.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def ask(api_key: str, model: str, image_path: Path, question: str) -> str:
    b64 = encode_image(image_path)
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_completion_tokens": 32,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["choices"][0]["message"]["content"]


def main() -> None:
    env = load_env(ROOT / ".env")
    api_key = env.get("OPENAI_API_KEY")
    model = env.get("OPENAI_MODEL", "gpt-5")
    if not api_key:
        print("OPENAI_API_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    print(f"Using model: {model}\n")

    synth_dir = ROOT / "runs" / "_diag_synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw

    def make_color(color):
        img = Image.new("RGB", (640, 480), color=(70, 90, 120))
        d = ImageDraw.Draw(img)
        d.rectangle([220, 180, 420, 300], fill=color)
        return img

    def make_pos(x_frac):
        img = Image.new("RGB", (640, 480), color=(70, 90, 120))
        d = ImageDraw.Draw(img)
        cx = int(640 * x_frac)
        d.rectangle([cx - 60, 180, cx + 60, 300], fill=(220, 30, 30))
        return img

    make_color((220, 20, 20)).save(synth_dir / "red.jpg")
    make_color((20, 20, 220)).save(synth_dir / "blue.jpg")
    make_color((20, 200, 20)).save(synth_dir / "green.jpg")
    make_pos(0.15).save(synth_dir / "left.jpg")
    make_pos(0.5).save(synth_dir / "center.jpg")
    make_pos(0.85).save(synth_dir / "right.jpg")

    color_q = "What color is the square in this image? Answer with exactly one word."
    print("--- color test (synthetic) ---")
    for name in ["red", "blue", "green"]:
        answer = ask(api_key, model, synth_dir / f"{name}.jpg", color_q)
        print(f"{name}.jpg -> {answer!r}")

    pos_q = (
        "Look at the red rectangle in this image. Is it on the LEFT side, the RIGHT side, or "
        "the CENTER of the image? Answer with exactly one word: LEFT, RIGHT, or CENTER."
    )
    print("\n--- position test (synthetic) ---")
    for name in ["left", "center", "right"]:
        answer = ask(api_key, model, synth_dir / f"{name}.jpg", pos_q)
        print(f"{name}.jpg -> {answer!r}")

    real_dir = ROOT / "runs" / "2026-08-15T232525Z_ep_vlm_pickup_001" / "frames"
    real_frames = [
        ("step_000_before.jpg", "CENTER (box was dead-center, far away)"),
        ("step_025_before.jpg", "CENTER or slightly LEFT"),
        ("step_050_before.jpg", "LEFT (clearly drifted left of center)"),
    ]
    print("\n--- position test (real saved sim frames) ---")
    for filename, expectation in real_frames:
        path = real_dir / filename
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        answer = ask(api_key, model, path, pos_q)
        print(f"{filename} -> {answer!r} (expected: {expectation})")


if __name__ == "__main__":
    main()
