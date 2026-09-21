"""Render recorded probe states from a clear overhead camera; never step physics."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    os.environ.setdefault("MUJOCO_GL", "egl")
    import imageio.v2 as imageio
    import mujoco
    import numpy as np
    from PIL import Image, ImageDraw

    from clear_path.audit import sha256

    source = args.run.resolve()
    rows = [
        json.loads(line) for line in (source / "state_trajectory.jsonl").read_text().splitlines()
    ]
    if not rows:
        raise ValueError("no recorded states")
    output = source / "overhead_replay"
    output.mkdir(exist_ok=False)
    model = mujoco.MjModel.from_xml_path(str(source / "scene.xml"))
    data = mujoco.MjData(model)
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 3.8, 120, -60
    frames = []
    with mujoco.Renderer(model, height=540, width=960) as renderer:
        with imageio.get_writer(output / "replay.mp4", fps=20, macro_block_size=2) as writer:
            for row in rows:
                data.qpos[:] = row["qpos"]
                data.qvel[:] = row["qvel"]
                data.time = row["time_s"]
                mujoco.mj_forward(model, data)
                x, y, _ = row["base_xyz"]
                camera.lookat[:] = [x + 0.4, y, 0.65]
                renderer.update_scene(data, camera=camera)
                frame = Image.fromarray(renderer.render())
                draw = ImageDraw.Draw(frame)
                draw.rectangle((0, 0, 960, 32), fill="#0f172a")
                draw.text(
                    (12, 10),
                    f"RECORDED PHYSICS REPLAY | t={data.time:.2f}s | {row['phase']}",
                    fill="white",
                )
                pixels = np.asarray(frame).copy()
                writer.append_data(pixels)
                frames.append(pixels)
    imageio.mimsave(output / "replay.gif", frames, duration=50, loop=0)
    imageio.imwrite(output / "final_frame.png", frames[-1])
    provenance = {
        "source_run": str(source),
        "source_sha256": {
            name: sha256(source / name)
            for name in ("scene.xml", "state_trajectory.jsonl", "result.json")
        },
        "frames": len(frames),
        "fps": 20,
        "note": "Recorded states only; no new physics execution. Originals unchanged.",
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    (output / "report.html").write_text(
        """<!doctype html>
<meta charset='utf-8'>
<h1>기록된 물리 실행: 상부 시점 재생</h1>
<p>새로운 실행이 아닙니다. 기존 상태 기록을 다른 카메라로 렌더링했습니다.</p>
<video controls width='960' src='replay.mp4'>
</video>
<p>
<a href='replay.gif'>GIF</a>
 · <a href='../report.html'>원본 결과</a>
 · <a href='provenance.json'>출처</a>
</p>"""
    )
    print(f"REPLAY={output / 'report.html'}")


if __name__ == "__main__":
    main()
