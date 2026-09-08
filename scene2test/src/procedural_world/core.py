"""Single-source metric geometry, conservative navigation raster and legacy graph adapter."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import deque
from dataclasses import asdict, dataclass

import numpy as np

from scene_graph import ObjectNode, Relation, Role, SceneGraph, SupportSurface

VERSION = "procedural-world-v1"


@dataclass(frozen=True)
class Config:
    mode: str = "rooms"
    seed: int = 0
    width: int = 15
    height: int = 15
    cell_size_m: float = 1.2
    room_count: int = 4
    obstacle_count: int = 6
    wall_height_m: float = 2.4
    robot_radius_m: float = 0.3
    safety_margin_m: float = 0.05
    subdivisions: int = 6

    def validate(self):
        if self.mode not in {"maze", "rooms"}:
            raise ValueError("mode must be maze or rooms")
        for name in ("seed", "width", "height", "room_count", "obstacle_count", "subdivisions"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if not (9 <= self.width <= 51 and 9 <= self.height <= 51):
            raise ValueError("width and height must be in [9, 51]")
        if self.width % 2 == 0 or self.height % 2 == 0:
            raise ValueError("width and height must be odd")
        if not 2 <= self.room_count <= 30 or not 0 <= self.obstacle_count <= 100:
            raise ValueError("room_count must be [2,30]; obstacle_count [0,100]")
        if not 2 <= self.subdivisions <= 10:
            raise ValueError("subdivisions must be [2,10]")
        for name in ("cell_size_m", "wall_height_m", "robot_radius_m", "safety_margin_m"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.wall_height_m <= 0 or self.cell_size_m <= 0 or self.robot_radius_m <= 0:
            raise ValueError("cell size, wall height and robot radius must be positive")
        # A sufficient (not necessary) clearance bound for off-center raster samples.
        r = self.cell_size_m / self.subdivisions
        if (
            self.robot_radius_m + self.safety_margin_m + r * (1 + math.sqrt(2)) / 2
            >= self.cell_size_m / 2
        ):
            raise ValueError("corridor too narrow for footprint, margin and raster resolution")


@dataclass(frozen=True)
class Box:
    id: str
    category: str
    position: tuple[float, float, float]
    size: tuple[float, float, float]  # full extents, meters, world frame
    mutable: bool = False  # editable between episodes; static during physics


@dataclass(frozen=True)
class Region:
    id: str
    center: tuple[float, float]
    size: tuple[float, float]


@dataclass(frozen=True)
class SceneSpec:
    config: Config
    boxes: tuple[Box, ...]
    regions: tuple[Region, ...]
    connections: tuple[tuple[str, str], ...]
    spawn_xy: tuple[float, float]
    goal_xy: tuple[float, float]
    generator_version: str = VERSION

    def to_dict(self):
        return asdict(self)

    @property
    def revision(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    @property
    def scene_id(self):
        return f"{self.config.mode}_{self.config.seed}_{self.revision[:12]}"


def _neighbors(cell, width, height):
    x, y = cell
    for nx, ny in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
        if 0 <= nx < width and 0 <= ny < height:
            yield nx, ny


def _flood(blocked, start):
    h, w = blocked.shape
    if blocked[start[1], start[0]]:
        return {}
    parent = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for nxt in _neighbors(cell, w, h):
            if nxt not in parent and not blocked[nxt[1], nxt[0]]:
                parent[nxt] = cell
                queue.append(nxt)
    return parent


def navigation_map(spec: SceneSpec):
    """Mark a cell blocked if any part could violate a circular footprint clearance.

    Half the cell diagonal is added to the footprint radius. Thus the entire free
    cell, not only its center, is conservatively safe relative to static boxes.
    Four-connected path segments stay inside the union of these cells.
    """
    if hasattr(spec, "surfaces"):
        from .terrain import navigation_map as terrain_map

        return terrain_map(spec)
    cfg = spec.config
    resolution = cfg.cell_size_m / cfg.subdivisions
    w, h = cfg.width * cfg.subdivisions, cfg.height * cfg.subdivisions
    xx, yy = np.meshgrid((np.arange(w) + 0.5) * resolution, (np.arange(h) + 0.5) * resolution)
    radius = cfg.robot_radius_m + cfg.safety_margin_m
    padded = radius + resolution / math.sqrt(2)
    boundary_distance = np.minimum.reduce([xx, yy, w * resolution - xx, h * resolution - yy])
    occupied = np.zeros((h, w), dtype=bool)
    blocked = boundary_distance <= padded
    for box in spec.boxes:
        dx = np.maximum(np.abs(xx - box.position[0]) - box.size[0] / 2, 0)
        dy = np.maximum(np.abs(yy - box.position[1]) - box.size[1] / 2, 0)
        occupied |= (dx == 0) & (dy == 0)
        blocked |= dx * dx + dy * dy <= padded * padded

    def to_cell(xy):
        cell = int(xy[0] / resolution), int(xy[1] / resolution)
        if not (0 <= cell[0] < w and 0 <= cell[1] < h):
            raise ValueError("endpoint outside map")
        return cell

    start, goal = to_cell(spec.spawn_xy), to_cell(spec.goal_xy)
    parents = _flood(blocked, start)
    path = []
    if goal in parents:
        cursor = goal
        while cursor is not None:
            path.append(cursor)
            cursor = parents[cursor]
        path.reverse()
    path_world = [[(x + 0.5) * resolution, (y + 0.5) * resolution] for x, y in path]
    # Endpoint-to-cell-center segments remain in their conservative free cells.
    if path_world:
        path_world = [list(spec.spawn_xy), *path_world, list(spec.goal_xy)]
    return {
        "schema_version": 1,
        "scene_id": spec.scene_id,
        "scene_revision": spec.revision,
        "frame": "world_xy_m",
        "origin_xy_m": [0.0, 0.0],
        "row_axis": "+y",
        "column_axis": "+x",
        "resolution_m": resolution,
        "width": w,
        "height": h,
        "footprint": "circle",
        "robot_radius_m": cfg.robot_radius_m,
        "safety_margin_m": cfg.safety_margin_m,
        "raster_padding_m": resolution / math.sqrt(2),
        "occupied": occupied.astype(int).tolist(),
        "blocked": blocked.astype(int).tolist(),
        "start_cell": list(start),
        "goal_cell": list(goal),
        "path_cells": [list(p) for p in path],
        "path_xy_m": path_world,
        "path_length_m": sum(math.dist(a, b) for a, b in zip(path_world, path_world[1:])),
        "reachable": bool(path),
        "all_region_centers_reachable": all(to_cell(r.center) in parents for r in spec.regions),
        "validation_scope": "static circular footprint; not G1 dynamics or full-body clearance",
    }


def generate(config: Config) -> SceneSpec:
    config.validate()
    rng = random.Random(config.seed)
    w, h, scale = config.width, config.height, config.cell_size_m
    solid = np.ones((h, w), dtype=bool)
    regions, connections = [], []
    centers = []
    if config.mode == "maze":
        solid[1, 1] = False
        stack = [(1, 1)]
        while stack:
            x, y = stack[-1]
            choices = [
                (x + dx, y + dy)
                for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
                if 0 < x + dx < w - 1 and 0 < y + dy < h - 1 and solid[y + dy, x + dx]
            ]
            if not choices:
                stack.pop()
                continue
            nx, ny = rng.choice(choices)
            solid[(y + ny) // 2, (x + nx) // 2] = False
            solid[ny, nx] = False
            stack.append((nx, ny))
        centers = [(1, 1)]
    else:
        rectangles = []
        for _ in range(2000):
            rw, rh = rng.randint(3, 5), rng.randint(3, 5)
            x, y = rng.randint(1, w - rw - 1), rng.randint(1, h - rh - 1)
            if any(
                not (x + rw < a or a + aw < x or y + rh < b or b + ah < y)
                for a, b, aw, ah in rectangles
            ):
                continue
            rectangles.append((x, y, rw, rh))
            solid[y : y + rh, x : x + rw] = False
            center = (x + rw // 2, y + rh // 2)
            if centers:
                px, py = centers[-1]
                cx, cy = center
                solid[py, min(px, cx) : max(px, cx) + 1] = False
                solid[min(py, cy) : max(py, cy) + 1, cx] = False
                connections.append((f"room_{len(centers) - 1}", f"room_{len(centers)}"))
            centers.append(center)
            regions.append(
                Region(
                    f"room_{len(regions)}",
                    ((center[0] + 0.5) * scale, (center[1] + 0.5) * scale),
                    (rw * scale, rh * scale),
                )
            )
            # Use the true rectangle center, not the chosen interior waypoint.
            regions[-1] = Region(
                regions[-1].id,
                ((x + rw / 2) * scale, (y + rh / 2) * scale),
                (rw * scale, rh * scale),
            )
            if len(centers) == config.room_count:
                break
        if len(centers) != config.room_count:
            raise ValueError("cannot fit requested rooms; increase map size or reduce room_count")

    start = centers[0]
    coarse_parents = _flood(solid, start)
    goal = list(coarse_parents)[-1] if config.mode == "maze" else centers[-1]
    boxes = [
        Box(
            f"wall_{x}_{y}",
            "wall",
            ((x + 0.5) * scale, (y + 0.5) * scale, config.wall_height_m / 2),
            (scale, scale, config.wall_height_m),
        )
        for y in range(h)
        for x in range(w)
        if solid[y, x]
    ]
    spawn_xy = ((start[0] + 0.5) * scale, (start[1] + 0.5) * scale)
    goal_xy = ((goal[0] + 0.5) * scale, (goal[1] + 0.5) * scale)

    def build():
        return SceneSpec(
            config, tuple(boxes), tuple(regions), tuple(connections), spawn_xy, goal_xy
        )

    base = navigation_map(build())
    if not base["reachable"] or not base["all_region_centers_reachable"]:
        raise ValueError("generated layout has no footprint-valid connection")
    candidates = [cell for cell in coarse_parents if cell not in {start, goal}]
    rng.shuffle(candidates)
    added = 0
    for x, y in candidates:
        if added == config.obstacle_count:
            break
        size = scale * rng.uniform(0.2, 0.4)
        box = Box(
            f"obstacle_{added}",
            "obstacle",
            ((x + 0.5) * scale, (y + 0.5) * scale, 0.3),
            (size, size, 0.6),
            True,
        )
        boxes.append(box)
        nav = navigation_map(build())
        if nav["reachable"] and nav["all_region_centers_reachable"]:
            added += 1
        else:
            boxes.pop()
    if added != config.obstacle_count:
        raise ValueError(
            f"only {added} of {config.obstacle_count} obstacles fit without blocking paths"
        )
    return build()


def scene_graph(spec: SceneSpec) -> SceneGraph:
    if hasattr(spec, "surfaces"):
        from .terrain import extend_graph

        base = SceneSpec(
            spec.config,
            spec.boxes,
            spec.regions,
            spec.connections,
            spec.spawn_xy,
            spec.goal_xy,
            spec.generator_version,
        )
        graph = scene_graph(base)
        graph.scene_id = spec.scene_id
        graph.meta["scene_revision"] = spec.revision
        return extend_graph(graph, spec)
    cfg = spec.config
    objects = [
        ObjectNode(
            b.id,
            Role.OBSTACLE,
            list(b.position),
            list(b.size),
            b.mutable,
            "block",
            {"category": b.category, "collision_geom": b.id, "static_during_rollout": True},
        )
        for b in spec.boxes
    ]
    for region in spec.regions:
        objects.append(
            ObjectNode(
                region.id,
                "navigation_region",
                [*region.center, 0.0],
                [*region.size, 0.0],
                False,
                "zone",
            )
        )
    objects.extend(
        [
            ObjectNode(
                "spawn", "robot_spawn", [*spec.spawn_xy, 0.0], [0.2, 0.2, 0.0], False, "zone"
            ),
            ObjectNode(
                "goal", Role.DESTINATION, [*spec.goal_xy, 0.0], [0.2, 0.2, 0.0], False, "zone"
            ),
        ]
    )
    relations = [Relation("on", b.id, "floor") for b in spec.boxes]
    relations.extend(
        Relation(
            "connected_via_corridor",
            a,
            b,
            value={"undirected": True, "source": "generation_topology"},
        )
        for a, b in spec.connections
    )
    for region in spec.regions:
        for obj in objects:
            if obj.id == region.id or obj.role == "navigation_region":
                continue
            if all(
                abs(obj.position[i] - region.center[i]) + obj.size[i] / 2
                <= region.size[i] / 2 + 1e-9
                for i in (0, 1)
            ):
                relations.append(Relation("inside", obj.id, region.id))
    return SceneGraph(
        spec.scene_id,
        [
            SupportSurface(
                "floor",
                "plane",
                0.0,
                {"x": [0, cfg.width * cfg.cell_size_m], "y": [0, cfg.height * cfg.cell_size_m]},
            )
        ],
        objects,
        relations,
        meta={
            "source": "procedural_ground_truth",
            "frame": "world",
            "units": "meters",
            "scene_revision": spec.revision,
            "generator_version": VERSION,
            "seed": cfg.seed,
            "task_type": "navigation",
            "legacy_panda_afs_compatible": False,
        },
    )
