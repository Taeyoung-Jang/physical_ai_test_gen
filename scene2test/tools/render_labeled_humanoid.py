"""Render verified saved states with viewer-only labels and a human silhouette.

No mj_step, policy, API or edits to source archives. Labels never enter robot inputs.
"""

import argparse
import bisect
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def verified_archive(root):
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    hashes = {}
    for entry in manifest["artifacts"]:
        name = entry["path"]
        path = (root / name).resolve()
        if not path.is_relative_to(root) or name in hashes:
            raise ValueError("unsafe or duplicate artifact path")
        value = hashlib.sha256(path.read_bytes()).hexdigest()
        if value != entry["sha256"]:
            raise ValueError(f"artifact hash mismatch: {name}")
        hashes[name] = value
    if not {"scene.xml", "states.jsonl", "human_motion.jsonl", "result.json"} <= hashes.keys():
        raise ValueError("verified scene, states, human trace and result required")
    return hashes


def project(point, camera, width, height):
    """Perspective projection using the renderer's actual GL camera."""
    delta = np.asarray(point) - np.asarray(camera.pos)
    forward, up = np.asarray(camera.forward), np.asarray(camera.up)
    right = np.cross(forward, up)
    depth = float(delta @ forward)
    if depth <= 0:
        return None
    near = camera.frustum_near
    top, bottom = camera.frustum_top, camera.frustum_bottom
    half_width = camera.frustum_width / 2 or (top - bottom) * width / height / 2
    x = (float(delta @ right) * near / depth - camera.frustum_center) / half_width
    y = (float(delta @ up) * near / depth - (top + bottom) / 2) / ((top - bottom) / 2)
    return ((x + 1) * width / 2, (1 - y) * height / 2)


def add_human(scene, xy, time_s, moving):
    import mujoco

    def shape(kind, size, pos, color, end=None):
        if scene.ngeom >= scene.maxgeom:
            raise ValueError("viewer scene capacity exceeded")
        g = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            g,
            kind,
            np.asarray(size),
            np.asarray(pos),
            np.eye(3).ravel(),
            np.asarray(color, dtype=np.float32),
        )
        if end is not None:
            mujoco.mjv_connector(g, kind, size[0], np.asarray(pos), np.asarray(end))
        scene.ngeom += 1

    x, y = xy
    skin, shirt, pants = [0.91, 0.69, 0.48, 1], [0.02, 0.65, 0.65, 1], [0.07, 0.16, 0.24, 1]
    sphere, capsule = mujoco.mjtGeom.mjGEOM_SPHERE, mujoco.mjtGeom.mjGEOM_CAPSULE
    shape(sphere, [0.14, 0, 0], [x, y, 1.44], skin)
    shape(capsule, [0.14, 0, 0], [x, y, 0.86], shirt, [x, y, 1.15])
    swing = 0.07 * np.sin(time_s * 7) if moving else 0.0
    for side in (-1, 1):
        shape(
            capsule,
            [0.045, 0, 0],
            [x + side * 0.17, y, 1.15],
            shirt,
            [x + side * 0.17, y - side * swing, 0.75],
        )
        shape(
            capsule,
            [0.065, 0, 0],
            [x + side * 0.085, y, 0.81],
            pants,
            [x + side * 0.085, y + side * swing, 0.09],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args()
    if args.max_frames is not None and args.max_frames < 1:
        parser.error("max-frames must be positive")
    hashes = verified_archive(args.run)
    if args.output_dir.resolve().is_relative_to(args.run.resolve()):
        parser.error("output must be outside source archive")
    states = [json.loads(line) for line in (args.run / "states.jsonl").open()]
    humans = [json.loads(line) for line in (args.run / "human_motion.jsonl").open()]
    times, human_times = [s["time_s"] for s in states], [h["time_s"] for h in humans]
    if not states or not humans or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("nonempty ordered recorded states required")
    if any(b <= a for a, b in zip(human_times, human_times[1:])):
        raise ValueError("ordered human trace required")
    os.environ.setdefault("MUJOCO_GL", "egl")
    import imageio.v2 as imageio
    import mujoco

    model = mujoco.MjModel.from_xml_path(str((args.run / "scene.xml").resolve()))
    data = mujoco.MjData(model)
    human_geom = model.geom("human_proxy_1").id
    mocap = int(model.body_mocapid[model.body("crossing_human").id])
    if mocap < 0:
        raise ValueError("recorded crossing mocap body required")
    colors = {
        "human_proxy_1": "#00a6a6",
        "obstacle_1": "#7952bf",
        "obstacle_2": "#df5262",
        "clear_box_geom": "#ed941c",
    }
    for name, color in colors.items():
        model.geom_rgba[model.geom(name).id] = [
            int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)
        ] + [1]
    model.geom_rgba[human_geom, 3] = 0
    for i in range(model.ngeom):
        if model.geom(i).name.startswith("wall_"):
            model.geom_rgba[i, 3] = 0.22
    args.output_dir.mkdir(parents=True, exist_ok=False)
    width, height, fps = 960, 540, 12
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = [4, 0, 0.5]
    camera.distance, camera.azimuth, camera.elevation = 8.8, 90, -65
    count = int((times[-1] - times[0]) * fps) + 1
    if args.max_frames is not None:
        count = min(count, args.max_frames)
    with (
        mujoco.Renderer(model, height=height, width=width) as renderer,
        imageio.get_writer(args.output_dir / "labeled.mp4", fps=fps, macro_block_size=2) as video,
    ):
        for frame_index in range(count):
            target = times[0] + frame_index / fps
            j = min(len(states) - 1, bisect.bisect_left(times, target))
            if j and abs(times[j - 1] - target) < abs(times[j] - target):
                j -= 1
            state = states[j]
            k = min(len(humans) - 1, bisect.bisect_left(human_times, state["time_s"]))
            if k and abs(human_times[k - 1] - state["time_s"]) < abs(
                human_times[k] - state["time_s"]
            ):
                k -= 1
            human = humans[k]
            if abs(human["time_s"] - state["time_s"]) > 1e-6:
                raise ValueError("state and human sample timestamps differ")
            data.qpos[:], data.qvel[:], data.ctrl[:] = state["qpos"], state["qvel"], state["ctrl"]
            data.time = state["time_s"]
            data.mocap_pos[mocap] = [*human["center_xy_m"], 0.8]
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera=camera)
            add_human(renderer.scene, human["center_xy_m"], data.time, human["state"] == "crossing")
            frame = Image.fromarray(renderer.render())
            draw = ImageDraw.Draw(frame)
            draw.rectangle((0, 0, width, 54), fill="#102334")
            draw.text((15, 7), "G1 CROSSING TEST | Recorded-state replay", font=font, fill="white")
            draw.text(
                (15, 31),
                f"t={data.time:.2f}s   Human: {human['state'].upper()}   "
                f"Base-to-human center: {human['center_distance_m']:.2f}m",
                font=small,
                fill="#bce6eb",
            )
            labels = [
                ("G1 ROBOT", data.qpos[:3] + [0, 0, 0.8], "#15364a"),
                ("GOAL", [7, 0, 0.08], "#25884a"),
            ]
            for name, label in [
                ("human_proxy_1", "HUMAN"),
                ("obstacle_1", "OBSTACLE 1"),
                ("obstacle_2", "OBSTACLE 2"),
                ("clear_box_geom", "PUSHABLE BOX"),
            ]:
                g = model.geom(name).id
                point = data.geom_xpos[g].copy()
                point[2] += model.geom_size[g, 2] + 0.08
                labels.append((label, point, colors[name]))
            for label, point, color in labels:
                pixel = project(point, renderer.scene.camera[0], width, height)
                if pixel is None:
                    continue
                x, y = pixel
                box = draw.textbbox((0, 0), label, font=small)
                text_width = box[2] - box[0]
                x = min(width - text_width - 14, max(8, x - text_width / 2))
                y = min(height - 65, max(60, y - 20))
                draw.rounded_rectangle(
                    (x - 5, y - 3, x + text_width + 5, y + 18), radius=4, fill=color
                )
                draw.text((x, y), label, font=small, fill="white")
            draw.rectangle((0, height - 35, width, height), fill="#102334")
            draw.text(
                (12, height - 27),
                (
                    "Viewer labels / human silhouette only. "
                    "Original physics, policy images and outcomes unchanged."
                ),
                font=small,
                fill="white",
            )
            video.append_data(np.asarray(frame))
            if frame_index in (0, count // 2):
                frame.save(args.output_dir / f"preview_{frame_index:05}.png")
            if frame_index % 240 == 0:
                print(f"FRAME={frame_index}/{count}", flush=True)
    (args.output_dir / "provenance.json").write_text(
        json.dumps(
            {
                "source_run": str(args.run.resolve()),
                "source_artifact_hashes": hashes,
                "render_only": True,
                "physics_steps": 0,
                "policy_calls": 0,
                "frames": count,
                "fps": fps,
                "sample_selection": (
                    "nearest saved 20Hz robot state; timestamp-matched full-rate human pose"
                ),
                "view_changes": (
                    "human visual silhouette, display colors, object labels, "
                    "transparent walls, overview camera"
                ),
                "claim": (
                    "Viewer reconstruction of recorded poses; "
                    "no new rollout or change to original evidence"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"VIDEO={args.output_dir / 'labeled.mp4'}")


if __name__ == "__main__":
    main()
