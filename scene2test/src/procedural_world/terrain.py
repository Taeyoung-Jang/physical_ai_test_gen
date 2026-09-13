"""Versioned 2.5D static courses: analytic support surfaces and shared mesh geometry.

Planning limits are experiment assumptions, not certified G1 capabilities.
All surfaces are single-valued height functions; no bridges, gaps or moving bodies.
"""

import math
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass

import numpy as np

from .core import Box, Config, SceneSpec

VERSION = "terrain-course-v1"


@dataclass(frozen=True)
class Surface:
    id: str
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float = 0.0
    slope_x: float = 0.0
    slope_y: float = 0.0
    friction: float = 0.8
    category: str = "flat"

    def height(self, x, y):
        return self.z0 + self.slope_x * (x - self.x0) + self.slope_y * (y - self.y0)

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def vertices(self):
        xy = [(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)]
        return [[x, y, -0.1] for x, y in xy] + [[x, y, self.height(x, y)] for x, y in xy]


@dataclass(frozen=True)
class TerrainSpec(SceneSpec):
    surfaces: tuple[Surface, ...] = ()
    floor_friction: float = 0.8
    planning_max_slope_deg: float = 25.0
    planning_max_step_m: float = 0.22


def ground_height(spec, xy):
    return max([0.0, *(s.height(*xy) for s in getattr(spec, "surfaces", ()) if s.contains(*xy))])


def validate(spec):
    spec.config.validate()
    if spec.generator_version != VERSION:
        raise ValueError("unsupported terrain version")
    if not spec.surfaces or len(spec.surfaces) > 300:
        raise ValueError("terrain requires 1..300 surfaces")
    if (
        not 0.01 <= spec.floor_friction <= 2
        or not 0 <= spec.planning_max_slope_deg <= 40
        or not 0 <= spec.planning_max_step_m <= 0.4
    ):
        raise ValueError("invalid friction or planning limits")
    ids = {b.id for b in spec.boxes} | {"floor", "spawn", "goal"}
    for s in spec.surfaces:
        if not re.fullmatch(r"[A-Za-z0-9_]+", s.id) or s.id in ids:
            raise ValueError("duplicate or invalid surface id")
        ids.add(s.id)
        if not all(
            math.isfinite(v)
            for v in (s.x0, s.x1, s.y0, s.y1, s.z0, s.slope_x, s.slope_y, s.friction)
        ):
            raise ValueError("nonfinite terrain")
        if not (
            0 <= s.x0 < s.x1 <= spec.config.width * spec.config.cell_size_m
            and 0 <= s.y0 < s.y1 <= spec.config.height * spec.config.cell_size_m
        ):
            raise ValueError("surface outside floor or empty")
        heights = [p[2] for p in s.vertices()[4:]]
        if min(heights) < -1e-8 or max(heights) > 2 or not 0.01 <= s.friction <= 2:
            raise ValueError("surface heights must be [0,2] m and friction [.01,2]")
    for i, a in enumerate(spec.surfaces):
        for b in spec.surfaces[i + 1 :]:
            if (
                min(a.x1, b.x1) - max(a.x0, b.x0) > 1e-8
                and min(a.y1, b.y1) - max(a.y0, b.y0) > 1e-8
            ):
                raise ValueError("overlapping support surfaces")


def segment_traversable(spec, a, b):
    """Check slope and exact support-boundary height jumps along an XY segment."""
    a, b = np.asarray(a), np.asarray(b)
    delta = b - a
    cuts = {0.0, 1.0}
    for s in spec.surfaces:
        for axis, bounds in ((0, (s.x0, s.x1)), (1, (s.y0, s.y1))):
            if abs(delta[axis]) > 1e-12:
                cuts.update(t for edge in bounds if 0 < (t := (edge - a[axis]) / delta[axis]) < 1)
    cuts = sorted(cuts)
    previous = None
    for lo, hi in zip(cuts, cuts[1:]):
        p = a + delta * ((lo + hi) / 2)
        surface = next((s for s in spec.surfaces if s.contains(*p)), None)
        if surface is None:
            return False
        if (
            surface is not None
            and math.degrees(math.atan(math.hypot(surface.slope_x, surface.slope_y)))
            > spec.planning_max_slope_deg + 1e-9
        ):
            return False
        start, end = a + delta * lo, a + delta * hi
        h0 = surface.height(*start) if surface else 0.0
        h1 = surface.height(*end) if surface else 0.0
        if previous is not None and abs(h0 - previous) > spec.planning_max_step_m + 1e-8:
            return False
        previous = h1
    return True


def navigation_map(spec):
    from .core import navigation_map as flat_map

    validate(spec)
    base = SceneSpec(
        spec.config,
        spec.boxes,
        spec.regions,
        spec.connections,
        spec.spawn_xy,
        spec.goal_xy,
        spec.generator_version,
    )
    nav = flat_map(base)
    nav.update(scene_id=spec.scene_id, scene_revision=spec.revision, schema_version=2)
    resolution = nav["resolution_m"]
    shape = (nav["height"], nav["width"])
    heights, slopes = np.zeros(shape), np.zeros(shape)
    friction = np.full(shape, spec.floor_friction)
    blocked = np.array(nav["blocked"], dtype=bool)
    xx, yy = np.meshgrid(
        (np.arange(shape[1]) + 0.5) * resolution, (np.arange(shape[0]) + 0.5) * resolution
    )
    supported = np.zeros(shape, dtype=bool)
    for s in spec.surfaces:
        mask = (xx >= s.x0) & (xx <= s.x1) & (yy >= s.y0) & (yy <= s.y1)
        supported |= mask
        heights[mask] = s.height(xx[mask], yy[mask])
        slopes[mask] = math.degrees(math.atan(math.hypot(s.slope_x, s.slope_y)))
        friction[mask] = s.friction
    blocked |= ~supported | (slopes > spec.planning_max_slope_deg + 1e-9)
    start, goal = tuple(nav["start_cell"]), tuple(nav["goal_cell"])
    parents = {} if blocked[start[1], start[0]] else {start: None}
    queue = deque(parents)

    def center(cell):
        return [(cell[0] + 0.5) * resolution, (cell[1] + 0.5) * resolution]

    while queue:
        x, y = queue.popleft()
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            nx, ny = nxt
            if (
                0 <= nx < shape[1]
                and 0 <= ny < shape[0]
                and nxt not in parents
                and not blocked[ny, nx]
                and segment_traversable(spec, center((x, y)), center(nxt))
            ):
                parents[nxt] = (x, y)
                queue.append(nxt)
    path, cursor = [], goal
    if goal in parents:
        while cursor is not None:
            path.append(list(cursor))
            cursor = parents[cursor]
        path.reverse()
    points = [list(spec.spawn_xy), *[center(p) for p in path], list(spec.goal_xy)] if path else []
    nav.update(
        blocked=blocked.astype(int).tolist(),
        reachable=bool(path),
        path_cells=path,
        path_xy_m=points,
        path_length_m=sum(math.dist(a, b) for a, b in zip(points, points[1:])),
        height_m=heights.tolist(),
        slope_deg=slopes.tolist(),
        friction=friction.tolist(),
        path_xyz_m=[[*p, ground_height(spec, p)] for p in points],
        terrain_surfaces=[s.__dict__ for s in spec.surfaces],
        planning_max_slope_deg=spec.planning_max_slope_deg,
        planning_max_step_m=spec.planning_max_step_m,
        validation_scope=(
            "2.5D center path + circular obstacle clearance; "
            "configured slope/step limits are NOT G1 capability guarantees"
        ),
    )
    nav["all_region_centers_reachable"] = all(
        (int(r.center[0] / resolution), int(r.center[1] / resolution)) in parents
        for r in spec.regions
    )
    return nav


def add_geometry(root, body, spec, prefix=""):
    """Convex meshes are built from the same analytic top corners as the map."""
    asset = root.find("asset")
    if asset is None:
        asset = ET.SubElement(root, "asset")
    floor = body.find(f"geom[@name='{prefix}floor']")
    if floor is not None:
        floor.set("friction", f"{spec.floor_friction} .005 .0001")
        floor.set("priority", "1")
        floor.set("contype", "0")
        floor.set("conaffinity", "0")
        pos = floor.get("pos").split()
        pos[2] = "-.21"
        floor.set("pos", " ".join(pos))
    for s in spec.surfaces:
        ident = prefix + s.id
        ET.SubElement(
            asset,
            "mesh",
            name=ident + "_mesh",
            vertex=" ".join(str(v) for point in s.vertices() for v in point),
        )
        ET.SubElement(
            body,
            "geom",
            name=ident,
            type="mesh",
            mesh=ident + "_mesh",
            friction=f"{s.friction} .005 .0001",
            priority="2",
            condim="3",
            group="2",
            rgba=".35 .65 .85 1" if s.friction >= 0.4 else ".65 .35 .8 1",
        )
    for name, xy in (("spawn", spec.spawn_xy), ("goal", spec.goal_xy)):
        site = body.find(f"site[@name='{prefix}{name}']")
        if site is not None:
            site.set("pos", f"{xy[0]} {xy[1]} {ground_height(spec, xy) + 0.015}")


def extend_graph(graph, spec):
    from scene_graph import ObjectNode, Relation

    for s in spec.surfaces:
        vertices = np.array(s.vertices())
        lo, hi = vertices.min(axis=0), vertices.max(axis=0)
        graph.objects.append(
            ObjectNode(
                s.id,
                "traversable_surface",
                ((lo + hi) / 2).tolist(),
                (hi - lo).tolist(),
                False,
                "mesh",
                {
                    **s.__dict__,
                    "height_equation": "z0+slope_x*(x-x0)+slope_y*(y-y0)",
                    "collision_geom": "world_" + s.id,
                    "static_during_rollout": True,
                },
            )
        )
        graph.relations.append(Relation("on", s.id, "floor"))
    for a, b in zip(spec.surfaces, spec.surfaces[1:]):
        if abs(a.x1 - b.x0) < 1e-8 and min(a.y1, b.y1) > max(a.y0, b.y0):
            graph.relations.append(Relation("adjacent_surface", a.id, b.id))
    for name, xy in (("spawn", spec.spawn_xy), ("goal", spec.goal_xy)):
        graph.get_object(name).position[2] = ground_height(spec, xy)
    graph.meta.update(
        terrain_schema=VERSION,
        generator_version=spec.generator_version,
        floor_friction=spec.floor_friction,
        support_representation=(
            "analytic traversable_surface nodes; floor is noncolliding visual backing"
        ),
        planning_limits={
            "slope_deg": spec.planning_max_slope_deg,
            "step_m": spec.planning_max_step_m,
        },
    )
    return graph


def generate_course(settings):
    """Composable YAML-friendly course. Unknown keys are rejected to catch experiment typos."""
    allowed = {
        "seed",
        "width_m",
        "friction",
        "segments",
        "planning_max_slope_deg",
        "planning_max_step_m",
    }
    if set(settings) - allowed:
        raise ValueError(f"unknown course settings: {set(settings) - allowed}")
    seed = settings.get("seed", 0)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    rng = np.random.default_rng(seed)
    width, mu = settings.get("width_m", 3.0), settings.get("friction", 0.8)
    if not 1.2 <= width <= 8 or not 0.01 <= mu <= 2:
        raise ValueError("width_m must be [1.2,8], friction [.01,2]")
    sections = settings.get("segments", [])
    if not isinstance(sections, list) or not 1 <= len(sections) <= 12:
        raise ValueError("segments requires 1..12 sections")
    boxes, surfaces = [], []
    x, cy = 1.8, 8.1

    def surface(length, w, friction, category="flat", z=0.0, slope=0.0):
        nonlocal x
        surfaces.append(
            Surface(
                f"surface_{len(surfaces)}",
                x,
                x + length,
                cy - w / 2,
                cy + w / 2,
                z,
                slope,
                0.0,
                friction,
                category,
            )
        )
        for side in (-1, 1):
            boxes.append(
                Box(
                    f"wall_{len(boxes)}",
                    "wall",
                    (x + length / 2, cy + side * (w / 2 + 0.1), 1.5),
                    (length, 0.2, 3.0),
                )
            )
        x += length

    surface(2.0, width, mu)
    schemas = {
        "flat": {"length_m"},
        "friction": {"length_m"},
        "ramp": {"length_m", "angle_deg", "landing_m"},
        "stairs": {"step_height_m", "tread_m", "count", "landing_m"},
        "rough": {"length_m", "cell_length_m", "amplitude_m"},
        "obstacles": {"length_m", "count", "size_min_m", "size_max_m", "pattern"},
        "bottleneck": {"length_m", "gap_m"},
    }
    for section in sections:
        kind = section.get("kind")
        if kind not in schemas or set(section) - (schemas[kind] | {"kind", "width_m", "friction"}):
            raise ValueError(f"unknown section kind or keys: {section}")
        w, friction = section.get("width_m", width), section.get("friction", mu)
        length = section.get("length_m", 3.0)
        if not 1.2 <= w <= width or not 0.01 <= friction <= 2 or not 0.5 <= length <= 12:
            raise ValueError("invalid section width/friction/length")
        if kind in {"flat", "friction"}:
            surface(length, w, friction, kind)
        elif kind == "ramp":
            angle, landing = section.get("angle_deg", 5.0), section.get("landing_m", 1.0)
            if not 0 <= angle <= 30 or not 0.5 <= landing <= 4:
                raise ValueError("ramp angle must be [0,30], landing [.5,4]")
            slope = math.tan(math.radians(angle))
            surface(length, w, friction, "ramp_up", slope=slope)
            surface(landing, w, friction, "landing", z=length * slope)
            surface(length, w, friction, "ramp_down", z=length * slope, slope=-slope)
        elif kind == "stairs":
            step, tread, count = (
                section.get("step_height_m", 0.05),
                section.get("tread_m", 0.5),
                section.get("count", 3),
            )
            landing = section.get("landing_m", 1.0)
            if (
                type(count) is not int
                or not 1 <= count <= 12
                or not 0.01 <= step <= 0.3
                or not 0.25 <= tread <= 1.5
                or not 0.5 <= landing <= 4
            ):
                raise ValueError("invalid stair dimensions")
            for i in range(count):
                surface(tread, w, friction, "step_up", z=(i + 1) * step)
            surface(landing, w, friction, "landing", z=count * step)
            for i in reversed(range(count)):
                surface(tread, w, friction, "step_down", z=i * step)
        elif kind == "rough":
            cell, amplitude = section.get("cell_length_m", 0.5), section.get("amplitude_m", 0.04)
            if not 0.2 <= cell <= 2 or not 0 <= amplitude <= 0.2:
                raise ValueError("invalid roughness")
            count = math.ceil(length / cell)
            heights = [0.0, *rng.uniform(0, amplitude, max(0, count - 1)), 0.0]
            for a, b in zip(heights, heights[1:]):
                surface(length / count, w, friction, "rough", z=a, slope=(b - a) / (length / count))
        elif kind == "bottleneck":
            gap = section.get("gap_m", 1.5)
            if not 0.4 <= gap < w:
                raise ValueError("gap must be [.4, section width)")
            start = x
            surface(length, w, friction)
            for side in (-1, 1):
                boxes.append(
                    Box(
                        f"barrier_{len(boxes)}",
                        "barrier",
                        (start + length / 2, cy + side * (w + gap) / 4, 0.6),
                        (0.4, (w - gap) / 2, 1.2),
                    )
                )
        elif kind == "obstacles":
            count = section.get("count", 3)
            low, high = (
                np.array(section.get("size_min_m", [0.2, 0.2, 0.2])),
                np.array(section.get("size_max_m", [0.6, 0.6, 1.2])),
            )
            pattern = section.get("pattern", "random")
            if (
                type(count) is not int
                or not 0 <= count <= 30
                or low.shape != (3,)
                or high.shape != (3,)
                or not np.isfinite([low, high]).all()
                or np.any(low < 0.1)
                or np.any(high > 2)
                or np.any(high < low)
                or pattern not in {"random", "slalom"}
            ):
                raise ValueError("invalid obstacle sizes/count/pattern")
            start = x
            surface(length, w, friction)
            for i in range(count):
                size = rng.uniform(low, high)
                if size[0] >= length - 0.4 or size[1] >= w - 0.4:
                    raise ValueError("obstacle too large for section")
                px = (
                    start + (i + 1) * length / (count + 1)
                    if pattern == "slalom"
                    else rng.uniform(start + size[0] / 2 + 0.1, x - size[0] / 2 - 0.1)
                )
                py = (
                    cy + (-1 if i % 2 else 1) * (w / 2 - size[1] / 2 - 0.15)
                    if pattern == "slalom"
                    else rng.uniform(cy - w / 2 + size[1] / 2 + 0.1, cy + w / 2 - size[1] / 2 - 0.1)
                )
                box = Box(
                    f"obstacle_{i}_{len(boxes)}",
                    "obstacle",
                    (float(px), float(py), float(size[2] / 2)),
                    tuple(size.tolist()),
                    True,
                )
                if any(
                    all(
                        abs(a - b) < (sa + sb) / 2 - 1e-8
                        for a, b, sa, sb in zip(box.position, other.position, box.size, other.size)
                    )
                    for other in boxes
                ):
                    raise ValueError(
                        "sampled obstacle overlap; choose another seed or reduce density"
                    )
                boxes.append(box)
    surface(2.0, width, mu)
    for px in (1.7, x + 0.1):
        boxes.append(Box(f"wall_{len(boxes)}", "wall", (px, cy, 1.5), (0.2, width + 0.4, 3.0)))
    cells = max(9, math.ceil((x + 1.8) / 1.8))
    cells += 1 - cells % 2
    cfg = Config(
        seed=seed,
        width=cells,
        height=9,
        cell_size_m=1.8,
        wall_height_m=3.0,
        robot_radius_m=0.4,
        safety_margin_m=0.1,
        obstacle_count=sum(b.mutable for b in boxes),
    )
    spec = TerrainSpec(
        cfg,
        tuple(boxes),
        (),
        (),
        (2.8, cy),
        (x - 1, cy),
        VERSION,
        tuple(surfaces),
        mu,
        settings.get("planning_max_slope_deg", 25.0),
        settings.get("planning_max_step_m", 0.22),
    )
    validate(spec)
    return spec
