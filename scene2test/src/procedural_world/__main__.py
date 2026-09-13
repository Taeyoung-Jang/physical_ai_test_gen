"""Run: python -m procedural_world --mode rooms --seed 0."""

import argparse
from pathlib import Path

from .core import Config, generate
from .export import export_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["rooms", "maze"], default="rooms")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--width", type=int, default=15)
    parser.add_argument("--height", type=int, default=15)
    parser.add_argument("--room-count", type=int, default=4)
    parser.add_argument("--obstacle-count", type=int, default=6)
    parser.add_argument("--cell-size-m", type=float, default=1.2)
    parser.add_argument("--robot-radius-m", type=float, default=0.3)
    parser.add_argument("--safety-margin-m", type=float, default=0.05)
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/worlds")
    )
    parser.add_argument("--render-3d", action="store_true", help="Requires MuJoCo renderer")
    args = vars(parser.parse_args())
    output_root = args.pop("output_root")
    render = args.pop("render_3d")
    try:
        result = export_bundle(generate(Config(**args)), output_root, render=render)
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f"World generation failed: {exc}\n")
    print(result)


if __name__ == "__main__":
    main()
