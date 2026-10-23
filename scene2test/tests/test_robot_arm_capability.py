"""CPU measurements and real primitive collision; no policy/model/API execution."""

import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import capability, obstacles  # noqa: E402

BLOCK = {"id": "block", "shape": "box", "xy_m": [0.0, 0.0], "size_m": [0.08, 0.08, 0.1]}
XML = """<mujoco><option timestep="0.002" gravity="0 0 -9.81"/>
<worldbody><body name="table" pos="0 0 0.875">
<geom name="table_collision" type="box" size=".5 .6 .025"/>
</body><body name="robot" pos=".4 .4 1.1"><geom name="robot_geom" type="sphere" size=".02"/>
<site name="eef"/></body>
<body name="bowl" pos="0 0 1.2"><freejoint/>
<geom name="bowl_geom" type="sphere" size=".02" mass=".1"/></body>
<body name="plate" pos=".2 .2 .91"><geom name="plate_geom" type="sphere" size=".01"/></body>
</worldbody></mujoco>"""


@pytest.mark.parametrize(
    "bad",
    [
        dict(BLOCK, shape="mesh"),
        dict(BLOCK, size_m=[0, 0.1, 0.1]),
        dict(BLOCK, xy_m=[float("nan"), 0]),
        dict(BLOCK, id="bad/name"),
        dict(BLOCK, shape="cylinder", size_m=[0.08, 0.1, 0.1]),
    ],
)
def test_rejects_unsupported_obstacles(bad):
    with pytest.raises(ValueError):
        obstacles.checked([bad])


def test_duplicate_and_off_table_obstacles_rejected():
    with pytest.raises(ValueError):
        obstacles.checked([BLOCK, BLOCK])
    with pytest.raises(ValueError, match="outside table"):
        obstacles.inject(XML, [dict(BLOCK, xy_m=[0.4, 0], size_m=[0.3, 0.1, 0.1])])


def raw_sim(xml):
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return mujoco, model, data


def test_static_box_is_real_collision_geometry():
    mj, model, data = raw_sim(obstacles.inject(XML, [BLOCK]))
    gid = mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM, "s2t_obstacle_block_geom")
    assert model.geom_contype[gid] == model.geom_conaffinity[gid] == 1
    assert model.geom_group[gid] == 1 and model.geom_rgba[gid, 3] == 1
    assert np.allclose(model.geom_size[gid], [0.04, 0.04, 0.05])
    touched = False
    for _ in range(500):
        mj.mj_step(model, data)
        touched |= any(gid in (c.geom1, c.geom2) for c in data.contact[: data.ncon])
    assert touched
    bowl = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "bowl")
    assert data.xpos[bowl, 2] > 1.01  # sphere rests on obstacle, not tabletop .9


def test_cylinder_compiles_and_does_not_add_joints():
    mj, original, _ = raw_sim(XML)
    item = dict(BLOCK, shape="cylinder")
    _, model, _ = raw_sim(obstacles.inject(XML, [item]))
    assert model.nq == original.nq and model.nv == original.nv
    gid = mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM, "s2t_obstacle_block_geom")
    assert model.geom_type[gid] == mj.mjtGeom.mjGEOM_CYLINDER


def make_control(xml):
    mj, model, data = raw_sim(xml)

    class Model:
        _model = model

        def __getattr__(self, key):
            return getattr(model, key)

        def geom_id2name(self, i):
            return mj.mj_id2name(model, mj.mjtObj.mjOBJ_GEOM, i)

        def geom_name2id(self, name):
            return mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM, name)

        def body_name2id(self, name):
            return mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)

    class Data:
        _data = data
        body_xpos = data.xpos
        body_xquat = data.xquat

        def __getattr__(self, key):
            return getattr(data, key)

    class Sim:
        def __init__(self):
            self.model = Model()
            self.data = Data()

        def step(self):
            mj.mj_step(model, data)

    raw = types.SimpleNamespace(
        obj_body_id={
            "akita_black_bowl_1": mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "bowl"),
            "plate_1": mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "plate"),
        },
        objects_dict={"akita_black_bowl_1": types.SimpleNamespace(contact_geoms=["bowl_geom"])},
        robots=[
            types.SimpleNamespace(
                robot_model=types.SimpleNamespace(root_body="robot"),
                eef_site_id=mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE, "eef"),
            )
        ],
        workspace_offset=[0, 0, 0.9],
    )
    return types.SimpleNamespace(sim=Sim(), env=raw), data


def test_substep_recorder_detects_contact_without_changing_dynamics(tmp_path):
    xml = obstacles.inject(XML, [BLOCK])
    control, data = make_control(xml)
    baseline, reference = make_control(xml)
    recorder = obstacles.Recorder(control, tmp_path)
    try:
        for _ in range(500):
            control.sim.step()
            baseline.sim.step()
    finally:
        recorder.close()
    assert np.array_equal(data.qpos, reference.qpos)
    assert np.array_equal(data.qvel, reference.qvel)
    rows = [json.loads(x) for x in (tmp_path / "physics.jsonl").read_text().splitlines()]
    result = capability.measure(rows, expected_duration=1.0)
    assert len(rows) == 501 and result["status"] == "COMPLETE"
    assert result["contact"] and "bowl_obstacle" in result["contact_kinds"]
    assert result["contact_duration_s"]["bowl_obstacle"] > 0
    assert result["peak_obstacle_force_n"] > 0
    assert result["cause"] == "UNCONFIRMED"


def rows(n=20):
    return [
        {
            "time_s": i * 0.01,
            "dt_s": 0.01,
            "table_surface_z_m": 0.9,
            "bowl_xyz_m": [0, 0, 0.8],
            "plate_xyz_m": [0.1, 0.1, 0.9],
            "eef_xyz_m": [0, 0, 1.0],
            "contacts": [],
        }
        for i in range(n)
    ]


def test_below_table_event_requires_duration():
    assert capability.measure(rows(5))["fell_below_table"] is False
    result = capability.measure(rows(20))
    assert result["fell_below_table"] and result["contact"] is False


@pytest.mark.parametrize("corruption", ["gap", "missing", "nan", "duration"])
def test_missing_or_gapped_evidence_is_unknown(corruption):
    data = rows()
    expected = None
    if corruption == "gap":
        del data[5]
    elif corruption == "missing":
        del data[0]["contacts"]
    elif corruption == "nan":
        data[1]["bowl_xyz_m"][0] = float("nan")
    else:
        expected = 100.0
    result = capability.measure(data, expected)
    assert result["status"] == "UNKNOWN"
    assert result["contact"] is None and result["fell_below_table"] is None


def test_boundaries_do_not_assume_monotonic_or_physical_reachability():
    suite = json.loads(
        (Path(__file__).resolve().parents[1] / "config/robot_arm_capability_suite.json").read_text()
    )
    cases = suite["cases"][:3]
    outcomes = {
        c["id"]: {"status": "VALID", "task_outcome": o}
        for c, o in zip(cases, ["PASS", "FAIL", "PASS"])
    }
    report = capability.brackets(cases, outcomes)
    assert report["status"] == "OBSERVED_TRANSITION" and len(report["intervals"]) == 2
    assert all(r["plate_path_width_m"] > 0 for r in report["intervals"])
    cases[1] = deepcopy(cases[1])
    cases[1]["positions"]["bowl_x"] += 0.01
    assert capability.brackets(cases, outcomes)["status"] == "UNMATCHED_CONTROLS"


def test_partial_file_does_not_become_no_contact(tmp_path):
    (tmp_path / "physics.jsonl").write_text("{")
    result = capability.case_measure(tmp_path, {"status": "VALID", "steps": [1]})
    assert result["status"] == "UNKNOWN" and result["contact"] is None


def test_suite_worker_uses_exclusive_intent_and_does_not_change_task_outcome(tmp_path, monkeypatch):
    import importlib.util

    tool = Path(__file__).resolve().parents[1] / "tools/run_robot_arm_capability.py"
    sys.path.insert(0, str(tool.parent))
    spec = importlib.util.spec_from_file_location("capability_cli", tool)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    suite = json.loads(cli.DEFAULT.read_text())
    (tmp_path / "manifest.json").write_text(json.dumps({"suite": suite}))
    d = tmp_path / "attempt_00000"
    d.mkdir()
    (d / "robot_intent.json").write_text(json.dumps(suite["cases"][0]))
    monkeypatch.setattr(cli.search, "verify", lambda _: suite["experiment"])
    calls = []

    def run(c, case, directory):
        calls.append(case["id"])
        return {"status": "VALID", "task_outcome": "PASS", "steps": [1]}

    monkeypatch.setattr(cli.obstacles, "run", run)
    assert cli.worker(tmp_path, 0) == 0
    assert json.loads((d / "receipt.json").read_text())["task_outcome"] == "PASS"
    assert json.loads((d / "measurement.json").read_text())["status"] == "UNKNOWN"
    cli.check_evidence(d)
    with pytest.raises(FileExistsError):
        cli.worker(tmp_path, 0)
    assert len(calls) == 1
    (d / "receipt.json").write_text("{}")
    with pytest.raises(ValueError, match="evidence changed"):
        cli.check_evidence(d)


def test_report_does_not_promote_unsealed_receipt(tmp_path):
    suite = json.loads(
        (Path(__file__).resolve().parents[1] / "config/robot_arm_capability_suite.json").read_text()
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"suite": suite}))
    d = tmp_path / "attempt_00000"
    d.mkdir()
    (d / "receipt.json").write_text(json.dumps({"status": "VALID", "task_outcome": "PASS"}))
    result = capability.report(tmp_path)
    assert result["cases"][0]["execution_status"] == "UNVERIFIED_PENDING_FINALIZATION"
    assert result["cases"][0]["task_outcome"] is None
    assert result["cases"][0]["measurement"]["status"] == "UNKNOWN"


def test_boundary_midpoint_is_proposal_only():
    suite = json.loads(
        (Path(__file__).resolve().parents[1] / "config/robot_arm_capability_suite.json").read_text()
    )
    cases = suite["cases"][:3]
    outcomes = {
        c["id"]: {"status": "VALID", "task_outcome": o}
        for c, o in zip(cases, ["PASS", "FAIL", "FAIL"])
    }
    result = capability.brackets(cases, outcomes)
    assert len(result["intervals"]) == 1
    proposal = result["intervals"][0]["next_probe"]
    assert proposal["line_t"] == 0.25
    assert proposal["positions"]["bowl_x"] == -0.075
    assert proposal["execution"].startswith("not run")
