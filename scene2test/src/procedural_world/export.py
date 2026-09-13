"""Export one immutable bundle; all derived products share a SceneSpec revision."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .core import SceneSpec, navigation_map, scene_graph


def mujoco_xml(spec: SceneSpec) -> str:
    """Standalone static scene, intentionally without a robot or locomotion policy."""
    root = ET.Element("mujoco", model=spec.scene_id)
    ET.SubElement(root, "option", timestep="0.005", gravity="0 0 -9.81")
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "global", offwidth="960", offheight="720")
    body = ET.SubElement(root, "worldbody")
    cfg = spec.config
    sx, sy = cfg.width * cfg.cell_size_m, cfg.height * cfg.cell_size_m

    def numbers(values):
        return " ".join(f"{v:.12g}" for v in values)

    ET.SubElement(body, "light", pos=numbers([sx / 2, sy / 2, 12]), directional="true")
    ET.SubElement(
        body,
        "geom",
        name="floor",
        type="box",
        pos=numbers([sx / 2, sy / 2, -0.1]),
        size=numbers([sx / 2, sy / 2, 0.1]),
        rgba="0.83 0.85 0.88 1",
    )
    for box in spec.boxes:
        ET.SubElement(
            body,
            "geom",
            name=box.id,
            type="box",
            pos=numbers(box.position),
            size=numbers([s / 2 for s in box.size]),
            rgba="0.95 0.45 0.15 1" if box.mutable else "0.32 0.39 0.48 1",
            friction="0.8 0.005 0.0001",
        )
    for name, xy, color in (
        ("spawn", spec.spawn_xy, "0.1 0.8 0.4 1"),
        ("goal", spec.goal_xy, "0.9 0.2 0.3 1"),
    ):
        ET.SubElement(
            body,
            "site",
            name=name,
            type="cylinder",
            pos=numbers([*xy, 0.015]),
            size="0.2 0.01",
            rgba=color,
        )
    if hasattr(spec, "surfaces"):
        from .terrain import add_geometry

        add_geometry(root, body, spec)
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def preview(spec, nav, path: Path):
    """Deterministic metric top view (not a camera image or a robot trajectory)."""
    blocked, occupied = np.array(nav["blocked"]), np.array(nav["occupied"])
    pixels = np.full((*blocked.shape, 3), [238, 242, 246], dtype=np.uint8)
    pixels[blocked == 1] = [171, 183, 197]
    pixels[occupied == 1] = [49, 62, 80]
    for box in spec.boxes:
        if not box.mutable:
            continue
        r = nav["resolution_m"]
        for y in range(nav["height"]):
            for x in range(nav["width"]):
                if (
                    abs((x + 0.5) * r - box.position[0]) <= box.size[0] / 2
                    and abs((y + 0.5) * r - box.position[1]) <= box.size[1] / 2
                ):
                    pixels[y, x] = [239, 135, 57]
    image = Image.fromarray(pixels[::-1]).resize((720, 720), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (720, 780), "white")
    canvas.paste(image, (0, 60))
    draw = ImageDraw.Draw(canvas)
    cfg = spec.config

    def point(xy):
        return (
            xy[0] / (cfg.width * cfg.cell_size_m) * 720,
            60 + 720 - xy[1] / (cfg.height * cfg.cell_size_m) * 720,
        )

    # Rectangular worlds keep a square canvas; the metric map remains authoritative.
    if len(nav["path_xy_m"]) > 1:
        draw.line([point(p) for p in nav["path_xy_m"]], fill="#4389ed", width=3)
    for label, xy, color in (("S", spec.spawn_xy, "#12945d"), ("G", spec.goal_xy, "#df3352")):
        x, y = point(xy)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color)
        draw.text((x + 9, y - 7), label, fill="black")
    draw.text((12, 8), f"{spec.scene_id} | ground-truth layout, +Y up", fill="black")
    draw.text(
        (12, 26),
        "Dark: walls | Orange: obstacles | Gray: clearance | Blue: reference path",
        fill="black",
    )
    draw.text((12, 43), "Static circular-footprint path, NOT a G1 rollout", fill="black")
    canvas.save(path)


def render_3d(spec: SceneSpec, path: Path):
    """Actual MuJoCo camera rendering; use MUJOCO_GL=egl on headless Linux."""
    import mujoco

    model = mujoco.MjModel.from_xml_string(mujoco_xml(spec))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    camera = mujoco.MjvCamera()
    cfg = spec.config
    camera.lookat[:] = [cfg.width * cfg.cell_size_m / 2, cfg.height * cfg.cell_size_m / 2, 0]
    camera.distance = max(cfg.width, cfg.height) * cfg.cell_size_m * 1.8
    camera.azimuth = 120
    camera.elevation = -65
    with mujoco.Renderer(model, height=720, width=960) as renderer:
        renderer.update_scene(data, camera=camera)
        Image.fromarray(renderer.render()).save(path)


def export_bundle(spec: SceneSpec, output_root: Path, *, render: bool = False) -> Path:
    nav = navigation_map(spec)
    if not nav["reachable"] or not nav["all_region_centers_reachable"]:
        raise ValueError("refusing to export a disconnected world")
    graph = scene_graph(spec)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / spec.scene_id
    target.mkdir(exist_ok=False)  # Never overwrite existing evidence.
    for name, value in (
        ("scene_spec.json", spec.to_dict()),
        ("scene_graph.json", graph.to_dict()),
        ("navigation_map.json", nav),
    ):
        (target / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    (target / "scene.xml").write_text(mujoco_xml(spec) + "\n")
    preview(spec, nav, target / "preview.png")
    if hasattr(spec, "surfaces"):
        from .terrain_visualization import plot_terrain

        plot_terrain(spec, nav, target / "terrain_map.png")
    if render:
        render_3d(spec, target / "scene_3d.png")
    manifest = {
        "schema_version": 1,
        "scene_id": spec.scene_id,
        "scene_revision": spec.revision,
        "generator_version": spec.generator_version,
        "validation": {
            "static_path_exists": nav["reachable"],
            "all_region_centers_reachable": nav["all_region_centers_reachable"],
            "g1_rollout_verified": False,
            "server_registered": False,
        },
        "artifacts": {
            p.name: {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in sorted(target.iterdir())
        },
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return target
