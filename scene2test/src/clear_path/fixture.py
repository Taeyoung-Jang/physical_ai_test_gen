"""One dynamic box and side bay, compiled from shared world-coordinate geometry."""

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import deque

import numpy as np

from scene_graph import ObjectNode, Relation, SceneGraph, SupportSurface

from .contracts import CorridorFixture

SPAWN = (1.0, 0.0)
GOAL = (7.0, 0.0)
BOX_START = (4.0, 0.0)
BOX_TARGET = (4.0, 1.65)
BOX_SIZE = (0.8, 1.1, 0.7)
# Wall AABBs: xmin, xmax, ymin, ymax. Corridor plus a narrow-entry side bay.
WALLS = {
    "wall_south": (0, 8, -0.9, -0.8),
    "wall_west": (-0.1, 0, -0.9, 0.9),
    "wall_east": (8, 8.1, -0.9, 0.9),
    "wall_north_left": (0, 3.3, 0.8, 0.9),
    "wall_north_right": (4.7, 8, 0.8, 0.9),
    "bay_west": (3.2, 3.3, 0.8, 2.6),
    "bay_east": (4.7, 4.8, 0.8, 2.6),
    "bay_north": (3.3, 4.7, 2.5, 2.6),
}


def walls(config):
    if not isinstance(config, CorridorFixture):
        return WALLS
    h = config.corridor_width_m / 2
    return {
        "wall_south": (0, 8, -h - 0.1, -h),
        "wall_north": (0, 8, h, h + 0.1),
        "wall_west": (-0.1, 0, -h - 0.1, h + 0.1),
        "wall_east": (8, 8.1, -h - 0.1, h + 0.1),
    }


def box_start(config):
    if not isinstance(config, CorridorFixture):
        return BOX_START
    # Independent bounded axes cannot initially overlap box and wall.
    available = config.corridor_width_m / 2 - BOX_SIZE[1] / 2 - 0.05
    return (4.0, config.box_lateral_fraction * available)


def identity(config):
    payload = {
        "config": config.model_dump(),
        "walls": walls(config),
        "box_size": BOX_SIZE,
        "spawn": SPAWN,
        "goal": GOAL,
        "box_start": box_start(config),
        "box_target": BOX_TARGET,
    }
    if isinstance(config, CorridorFixture):
        del payload["box_target"]  # no prescribed object destination in the new scene
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def navigation_map(config, box_xy=None, *, hypothetical=False):
    """Conservative circular-footprint grid at fixed 5 cm resolution; 4-neighbor BFS."""
    box_xy = np.asarray(box_start(config) if box_xy is None else box_xy, dtype=float)
    if box_xy.shape != (2,) or not np.isfinite(box_xy).all():
        raise ValueError("box center must be finite world xy")
    corridor = isinstance(config, CorridorFixture)
    resolution = 0.05
    x_origin, y_origin, nx, ny = -0.1, -1.0, 164, 74
    if corridor:
        # Match the planner's bounds from the actual floor center and half size.
        # Literal -0.2 rounds differently from 4-4.2 at exact grid boundaries.
        x_origin, y_origin = 4.0 - 4.2, 0.0 - 2.2
        nx, ny = int((4.0 + 4.2 - x_origin) / resolution), int(4.4 / resolution)
    x, y = np.meshgrid(
        (np.arange(nx) + 0.5) * resolution + x_origin,
        (np.arange(ny) + 0.5) * resolution + y_origin,
    )
    inside = ((x >= 0) & (x <= 8) & (y >= -0.8) & (y <= 0.8)) | (
        (x >= 3.3) & (x <= 4.7) & (y >= 0.8) & (y <= 2.5)
    )
    if corridor:
        h = config.corridor_width_m / 2
        inside = (x >= 0) & (x <= 8) & (y >= -h) & (y <= h)
    blocked = ~inside
    rects = [
        *walls(config).values(),
        (box_xy[0] - 0.4, box_xy[0] + 0.4, box_xy[1] - 0.55, box_xy[1] + 0.55),
    ]
    radius = config.footprint_radius_m + config.clearance_m
    if corridor:
        radius = round(radius, 12)  # default 0.40 exactly, matching robot-local planner
    for x0, x1, y0, y1 in rects:
        dx, dy = (
            np.maximum(np.maximum(x0 - x, x - x1), 0),
            np.maximum(np.maximum(y0 - y, y - y1), 0),
        )
        blocked |= dx * dx + dy * dy <= radius * radius

    def cell(xy):
        return int((xy[1] - y_origin) / resolution), int((xy[0] - x_origin) / resolution)

    start, goal = cell(SPAWN), cell(GOAL)
    parents, queue = {start: None}, deque([start] if not blocked[start] else [])
    while queue:
        a = queue.popleft()
        if a == goal:
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            b = a[0] + dy, a[1] + dx
            if (
                0 <= b[0] < blocked.shape[0]
                and 0 <= b[1] < blocked.shape[1]
                and b not in parents
                and not blocked[b]
            ):
                parents[b] = a
                queue.append(b)
    path, current = [], goal if goal in parents and not blocked[start] else None
    while current is not None:
        path.append([float(x[current]), float(y[current])])
        current = parents[current]
    return {
        "schema_version": "clear-path-map-v2" if corridor else "clear-path-map-v1",
        **({"scene_revision": identity(config)} if corridor else {}),
        "frame": "world_m",
        "state_version": 0,
        "hypothetical": hypothetical,
        "box_xy_m": box_xy.tolist(),
        "resolution_m": resolution,
        "origin_xy_m": [x_origin, y_origin],
        "effective_radius_m": radius,
        "blocked": blocked.astype(int).tolist(),
        "reachable": bool(path),
        "path_xy_m": path[::-1],
        "note": "Static circular-footprint test; NOT a whole-body manipulation oracle",
    }


def graph(config):
    revision = identity(config)
    objects = [
        ObjectNode(
            name,
            "obstacle",
            [(a + b) / 2, (c + d) / 2, 0.6],
            [b - a, d - c, 1.2],
            movable=False,
            extra={"contact_annotation": "diagnostic_only"}
            if isinstance(config, CorridorFixture)
            else {"forbidden_contact": True},
        )
        for name, (a, b, c, d) in walls(config).items()
    ]
    objects += [
        ObjectNode(
            "clear_box",
            "obstacle",
            [*box_start(config), BOX_SIZE[2] / 2],
            list(BOX_SIZE),
            extra={
                "mass_kg": config.box_mass_kg,
                "sliding_friction": config.box_friction,
                "dynamic": True,
                "manipulation_feasibility": "unverified",
            },
        ),
        ObjectNode(
            "push_goal",
            "destination",
            [*BOX_TARGET, 0],
            [0.8, 1.1, 0.01],
            movable=False,
            shape="zone",
            extra={"physical_collision": False},
        ),
        ObjectNode(
            "robot_goal",
            "destination",
            [*GOAL, 0],
            [0.2, 0.2, 0.01],
            movable=False,
            shape="zone",
            extra={"physical_collision": False},
        ),
    ]
    corridor = isinstance(config, CorridorFixture)
    if corridor:
        objects = [o for o in objects if o.id != "push_goal"]
        for obj in objects:
            if obj.role == "obstacle":
                obj.extra["mujoco_geom_name"] = (
                    "clear_box_geom" if obj.id == "clear_box" else obj.id
                )
    return SceneGraph(
        scene_id="clear_path_" + revision[:12],
        support_surfaces=[
            SupportSurface(
                "clear_floor",
                "plane",
                0,
                {
                    "x": [0, 8],
                    "y": [-config.corridor_width_m / 2, config.corridor_width_m / 2]
                    if corridor
                    else [-0.8, 2.5],
                },
            )
        ],
        objects=objects,
        relations=[Relation("on", "clear_box", "clear_floor")],
        meta={
            "task": "goal_navigation@0.1" if corridor else "clear_path@0.1",
            "scene_revision": revision,
            "frame": "world_m",
            "state_version": 0,
            "source": "trusted_simulator_geometry",
            "robot_rollout": False,
            "floor_bounds_are_not_navigation_free_space": True,
        },
    ).to_dict()


def world_xml(config, robot_source=None):
    """Append object AFTER robot joints; no new actuators. Original robot files untouched."""
    from pathlib import Path

    if robot_source:
        source = Path(robot_source)
        root = ET.parse(source).getroot()
        compiler = root.find("compiler")
        compiler.set("meshdir", str((source.parent / compiler.get("meshdir", "")).resolve()))
        if root.find("keyframe") is not None:
            raise ValueError("keyframe resizing must be implemented before this robot is supported")
        wb = root.find("worldbody")
        for worldbody in root.findall("worldbody"):
            for child in list(worldbody):
                if child.tag == "geom":
                    worldbody.remove(child)
        pelvis = wb.find("body[@name='pelvis']")
        if pelvis is None:
            raise ValueError("expected G1 pelvis")
        pos = [float(v) for v in pelvis.get("pos", "0 0 0").split()]
        pelvis.set("pos", f"{SPAWN[0]} {SPAWN[1]} {pos[2]}")
        torso = wb.find(".//body[@name='torso_link']")
        ET.SubElement(
            torso,
            "camera",
            name="clear_robot_camera",
            pos=".15 0 .35",
            xyaxes="0 -1 0 0 0 1",
            fovy="65",
        )
        for side in ("left", "right"):
            wrist = wb.find(f".//body[@name='{side}_wrist_yaw_link']")
            ET.SubElement(
                wrist,
                "site",
                name=f"{side}_push_site",
                pos=next(
                    g for g in wrist.findall("geom") if g.get("mesh") == f"{side}_hand_palm_link"
                ).get("pos", "0 0 0"),
                size=".01",
                rgba="1 .2 .2 1",
            )
    else:
        root = ET.Element("mujoco", model="clear_path_fixture")
        wb = ET.SubElement(root, "worldbody")
    visual = root.find("visual")
    if visual is None:
        visual = ET.SubElement(root, "visual")
    global_view = visual.find("global")
    if global_view is None:
        global_view = ET.SubElement(visual, "global")
    global_view.set("offwidth", "960")
    global_view.set("offheight", "540")
    option = root.find("option")
    if option is None:
        option = ET.SubElement(root, "option")
    option.set("timestep", ".005")
    ET.SubElement(wb, "light", pos="3 -2 6", dir="0 0 -1", diffuse=".8 .8 .8")
    ET.SubElement(
        wb,
        "geom",
        name="clear_floor",
        type="box",
        size="4.2 2.2 .1" if isinstance(config, CorridorFixture) else "4.2 2 .1",
        pos="4 0 -.1" if isinstance(config, CorridorFixture) else "4 .8 -.1",
        friction=f"{config.floor_friction} .005 .0001",
        rgba=".72 .76 .8 1",
    )
    for name, (a, b, c, d) in walls(config).items():
        ET.SubElement(
            wb,
            "geom",
            name=name,
            type="box",
            pos=f"{(a + b) / 2} {(c + d) / 2} .6",
            size=f"{(b - a) / 2} {(d - c) / 2} .6",
            rgba=".25 .3 .4 1",
        )
    start = box_start(config)
    body = ET.SubElement(wb, "body", name="clear_box", pos=f"{start[0]} {start[1]} .35")
    ET.SubElement(body, "freejoint", name="clear_box_free")
    ET.SubElement(
        body,
        "geom",
        name="clear_box_geom",
        type="box",
        size=".4 .55 .35",
        mass=str(config.box_mass_kg),
        friction=f"{config.box_friction} .005 .0001",
        rgba="1 .5 .05 1",
    )
    for name, (x, y), size, color in (
        ("push_goal", BOX_TARGET, ".4 .55 .002", ".1 .8 .3 .6"),
        ("robot_goal", GOAL, ".15 .15 .002", ".1 .4 1 .8"),
    ):
        if name == "push_goal" and isinstance(config, CorridorFixture):
            continue
        ET.SubElement(wb, "site", name=name, type="box", size=size, pos=f"{x} {y} .004", rgba=color)
    return ET.tostring(root, encoding="unicode")
