"""Static primitive obstacles and physics-substep evidence for a new development condition."""

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from robot_arm import placement

PREFIX = "s2t_obstacle_"


def checked(items):
    if not isinstance(items, list) or len(items) > 4:
        raise ValueError("obstacles must be a list of at most four primitives")
    ids = set()
    for item in items:
        if set(item) != {"id", "shape", "xy_m", "size_m"}:
            raise ValueError("obstacle requires id/shape/xy_m/size_m")
        name = item["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,31}", name):
            raise ValueError("invalid obstacle ID")
        if name in ids or item["shape"] not in {"box", "cylinder"}:
            raise ValueError("duplicate ID or unsupported primitive")
        ids.add(name)
        xy, size = item["xy_m"], item["size_m"]
        if not isinstance(xy, list) or not isinstance(size, list) or len(xy) != 2 or len(size) != 3:
            raise ValueError("XY and full XYZ dimensions required")
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in xy + size):
            raise ValueError("finite numeric obstacle dimensions required")
        if any(abs(x) > 0.4 for x in xy) or not all(0.01 <= x <= 0.30 for x in size):
            raise ValueError("obstacle bounds: XY +/-0.4m; full dimensions .01..0.30m")
        if item["shape"] == "cylinder" and size[0] != size[1]:
            raise ValueError("cylinder XY dimensions must be equal diameters")
    return items


def inject(xml, items):
    checked(items)
    root = ET.fromstring(xml)
    table = root.find(".//body[@name='table']")
    if table is None:
        raise ValueError("expected existing table body")
    geom = table.find("geom[@name='table_collision']")
    if geom is None or geom.get("type", "sphere") != "box":
        raise ValueError("box table collision surface required")
    if table.get("quat", "1 0 0 0") != "1 0 0 0" or any(
        table.get(k) for k in ("euler", "axisangle")
    ):
        raise ValueError("rotated table unsupported")
    half = [float(x) for x in geom.get("size").split()]
    center = [float(x) for x in geom.get("pos", "0 0 0").split()]
    top = center[2] + half[2]
    for item in items:
        name = PREFIX + item["id"]
        if root.find(f".//*[@name='{name}']") is not None:
            raise ValueError("obstacle already inserted or name collision")
        x, y = item["xy_m"]
        w, d, h = item["size_m"]
        if abs(x) + w / 2 > half[0] or abs(y) + d / 2 > half[1]:
            raise ValueError("obstacle footprint outside table")
        body = ET.SubElement(table, "body", name=name, pos=f"{x} {y} {top + h / 2}")
        dimensions = f"{w / 2} {d / 2} {h / 2}" if item["shape"] == "box" else f"{w / 2} {h / 2}"
        ET.SubElement(
            body,
            "geom",
            name=name + "_geom",
            type=item["shape"],
            size=dimensions,
            contype="1",
            conaffinity="1",
            group="1",
            rgba="0.95 0.25 0.08 1",
            friction="1 0.005 0.0001",
        )
    return ET.tostring(root, encoding="unicode")


def obstacle_ids(control):
    sim = control.sim
    return {
        i for i in range(sim.model.ngeom) if (sim.model.geom_id2name(i) or "").startswith(PREFIX)
    }


def initial_check(control):
    sim = control.sim
    ids = obstacle_ids(control)
    problems = []
    for i in range(sim.data.ncon):
        c = sim.data.contact[i]
        if int(c.geom1) not in ids and int(c.geom2) not in ids:
            continue
        names = [sim.model.geom_id2name(int(g)) or "" for g in (c.geom1, c.geom2)]
        if any(n.startswith("table") for n in names):
            continue
        if float(c.dist) < -1e-6:
            problems.append({"geoms": names, "distance_m": float(c.dist)})
    return problems


class Recorder:
    def __init__(self, control, directory):
        self.control = control
        self.directory = Path(directory)
        self.stream = (self.directory / "physics.jsonl").open("x")
        sim, raw = control.sim, control.env
        self.obstacles = obstacle_ids(control)
        self.bowl = {
            sim.model.geom_name2id(g) for g in raw.objects_dict["akita_black_bowl_1"].contact_geoms
        }
        robot_root = sim.model.body_name2id(raw.robots[0].robot_model.root_body)
        self.robot = set()
        for gid in range(sim.model.ngeom):
            body = int(sim.model.geom_bodyid[gid])
            while body and body != robot_root:
                body = int(sim.model.body_parentid[body])
            if body == robot_root:
                self.robot.add(gid)
        self.original_step = sim.step
        self.dt = float(sim.model.opt.timestep)
        self.surface = float(raw.workspace_offset[2])
        self.count = 0
        self.sample()

        def step(*args, **kwargs):
            value = self.original_step(*args, **kwargs)
            self.sample()
            return value

        sim.step = step

    def sample(self):
        import mujoco
        import numpy as np

        sim, raw = self.control.sim, self.control.env
        contacts = []
        for i in range(sim.data.ncon):
            c = sim.data.contact[i]
            a, b = int(c.geom1), int(c.geom2)
            if a not in self.obstacles and b not in self.obstacles:
                continue
            other = b if a in self.obstacles else a
            if other in self.obstacles:
                kind = "obstacle_obstacle"
            elif other in self.robot:
                kind = "robot_obstacle"
            elif other in self.bowl:
                kind = "bowl_obstacle"
            else:
                continue
            force = np.zeros(6)
            mujoco.mj_contactForce(sim.model._model, sim.data._data, i, force)
            contacts.append(
                {
                    "kind": kind,
                    "geoms": [sim.model.geom_id2name(g) for g in (a, b)],
                    "distance_m": float(c.dist),
                    "force_n": float(np.linalg.norm(force[:3])),
                }
            )
        state = placement.snapshot(self.control)
        row = {
            "time_s": float(sim.data.time),
            "dt_s": self.dt,
            "table_surface_z_m": self.surface,
            "bowl_xyz_m": state["akita_black_bowl_1"]["xyz_m"],
            "plate_xyz_m": state["plate_1"]["xyz_m"],
            "eef_xyz_m": sim.data.site_xpos[raw.robots[0].eef_site_id].tolist(),
            "contacts": contacts,
        }
        self.stream.write(json.dumps(row, allow_nan=False) + "\n")
        self.count += 1
        if self.count % 25 == 0:
            self.stream.flush()

    def close(self):
        self.stream.close()


def run(config, candidate, directory):
    """Reuse unchanged upstream policy and placement; instrument only this worker process."""
    import os
    import sys

    items = checked(candidate["obstacles"])
    os.environ["LIBERO_CONFIG_PATH"] = config["robot"]["libero_config_path"]
    sys.path.insert(0, config["robot"]["upstream_root"])
    from gr00t.eval.sim.LIBERO import libero_env

    original_init = libero_env.LiberoEnv.__init__
    original_apply = placement.apply
    recorders = []

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._env.env.set_xml_processor(lambda xml: inject(xml, items))

    def apply(control, values, background=None):
        audit = original_apply(control, values, background)
        if control.env.control_freq != 20:
            raise ValueError("measurement contract requires LIBERO 20Hz control")
        sim = control.sim
        actual = [
            {
                "name": sim.model.geom_id2name(g),
                "xyz_m": sim.data.geom_xpos[g].tolist(),
                "size": sim.model.geom_size[g].tolist(),
                "contype": int(sim.model.geom_contype[g]),
                "conaffinity": int(sim.model.geom_conaffinity[g]),
            }
            for g in sorted(obstacle_ids(control))
        ]
        audit["obstacles"] = {
            "requested": items,
            "compiled": actual,
            "initial_penetrations": initial_check(control),
        }
        if len(actual) != len(items):
            audit["problems"].append("missing_compiled_obstacle")
        if audit["obstacles"]["initial_penetrations"]:
            audit["problems"].append("obstacle_initial_penetration")
        audit["valid"] = not audit["problems"]
        (directory / "scene.xml").write_text(sim.model.get_xml())
        if audit["valid"]:
            recorders.append(Recorder(control, directory))
        return audit

    libero_env.LiberoEnv.__init__ = init
    placement.apply = apply
    try:
        return placement.run_episode(config, candidate, directory)
    finally:
        placement.apply = original_apply
        libero_env.LiberoEnv.__init__ = original_init
        for recorder in recorders:
            recorder.close()
