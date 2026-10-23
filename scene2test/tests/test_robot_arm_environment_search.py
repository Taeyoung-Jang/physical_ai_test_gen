"""CPU-only isolation, shared-domain, durable-resume and contact/outcome contracts."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import environment_search as x
from robot_arm import placement, search


@pytest.fixture
def prepared(tmp_path):
    design = search.read(
        Path(__file__).resolve().parents[1] / "config/robot_arm_environment_comparison.json"
    )
    c = design["experiment"]
    c["seeds"] = [641, 647]
    c["robot"]["model_path"] = str(tmp_path / "model")
    Path(c["robot"]["model_path"]).mkdir()
    root = tmp_path / "campaign"
    root.mkdir()
    m = search.freeze(c, [])
    m.update(mode=x.VERSION, design=design)
    placement.save(root / "manifest.json", m)
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json"))
    return root, design


def fake_runner(c, value, d):
    placement.save(d / "receipt.json", {"status": "VALID", "task_outcome": "PASS"})
    placement.save(d / "measurement.json", {"status": "COMPLETE", "contact": True})
    x.seal(d)


def proposer(body):
    # OpenRouter chat wire; no live calls.
    context = json.loads(body["messages"][-1]["content"][0]["text"])
    values = {a: sum(v) / 2 for a, v in context["shared_domain"].items()}
    return {
        "model": "openai/gpt-6-luna-pro",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"parameters": values, "hypothesis": "mock"}),
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_shared_bootstrap_seeds_and_history_isolation(prepared):
    root, design = prepared
    seen = []
    contexts = []

    def run(c, v, d):
        seen.append((d, v))
        fake_runner(c, v, d)

    def propose(body):
        ctx = json.loads(body["messages"][-1]["content"][0]["text"])
        contexts.append(ctx)
        assert all("/afs/" in r["evidence_id"] for r in ctx["history"])
        assert len({r["evidence_id"].split("/")[0] for r in ctx["history"]}) == 1
        return proposer(body)

    out = x.run(root, run, propose, 24)
    assert out["equal_valid_budget_complete"]
    assert out["totals"]["afs"]["unique_environment_settings"] == 5
    assert out["totals"]["afs"]["repeated_environment_settings"] == 3
    assert len(seen) == 16 and len(contexts) == 4
    assert all(t["fail"] == 0 and t["contact_pass"] == 8 for t in out["totals"].values())
    for s in design["experiment"]["seeds"]:
        for i in range(2):
            a = search.read(root / f"seed_{s}/afs/attempt_{i:05d}/candidate.json")
            b = search.read(root / f"seed_{s}/random/attempt_{i:05d}/candidate.json")
            assert a == b
    # Reconstruction must exclude current AND later outcomes; complete resume spends nothing.
    assert (
        x.run(root, lambda *a: pytest.fail("robot rerun"), lambda *a: pytest.fail("API resend"), 24)
        == out
    )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 0.31, -1])
def test_domain_rejects_invalid(prepared, value):
    _, d = prepared
    p = x.uniform(d, 641, 0)
    p["obstacle_height"] = value
    with pytest.raises(ValueError):
        x.checked(d, p)


def test_uniform_shared_domain(prepared):
    _, d = prepared
    for seed in d["experiment"]["seeds"]:
        for i in range(4):
            p = x.uniform(d, seed, i)
            assert p == x.uniform(d, seed, i)
            assert x.checked(d, p) == p


def test_pending_robot_never_reruns(prepared):
    root, _ = prepared

    def crash(*args):
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        x.run(root, crash, proposer, 1)
    with pytest.raises(RuntimeError, match="pending robot"):
        x.run(root, fake_runner, proposer, 1)


def test_ambiguous_api_never_resends(prepared):
    root, _ = prepared
    x.run(root, fake_runner, proposer, 8)

    def crash(*a):
        raise RuntimeError("timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        x.run(root, fake_runner, crash, 1)
    with pytest.raises(RuntimeError, match="never resend"):
        x.run(root, fake_runner, proposer, 1)


def test_saved_response_collection(prepared):
    root, _ = prepared
    x.run(root, fake_runner, proposer, 8)

    def crash(c, v, d):
        raise RuntimeError("before-result")

    with pytest.raises(RuntimeError):
        x.run(root, crash, proposer, 1)
    # A worker receipt can be collected without a second API or robot call.
    d = root / "seed_641/afs/attempt_00002"
    fake_runner({}, search.read(d / "candidate.json"), d)
    out = x.run(root, fake_runner, proposer, 1)
    assert out["totals"]["afs"]["afs_requests"] == 1


def test_saved_candidate_tamper(prepared):
    root, _ = prepared
    x.run(root, fake_runner, proposer, 1)
    d = root / "seed_641/afs/attempt_00000"
    v = search.read(d / "candidate.json")
    v["parameters"]["obstacle_height"] = 0.10
    (d / "candidate.json").write_text(json.dumps(v))
    with pytest.raises(ValueError, match="candidate differs"):
        x.run(root, fake_runner, proposer, 1)


def test_exclusion_not_failure_and_stops(prepared):
    root, _ = prepared

    def excluded(c, v, d):
        placement.save(d / "receipt.json", {"status": "INCONCLUSIVE", "task_outcome": None})
        placement.save(d / "measurement.json", {"status": "UNKNOWN", "contact": None})
        x.seal(d)

    with pytest.raises(RuntimeError, match="excluded"):
        x.run(root, excluded, proposer, 24)
    s = x.summary(root)["totals"]["afs"]
    assert s["excluded"] == 1 and s["fail"] == 0
    with pytest.raises(RuntimeError, match="excluded"):
        x.run(root, fake_runner, proposer, 24)


def test_out_of_domain_response_no_robot(prepared):
    root, _ = prepared
    x.run(root, fake_runner, proposer, 8)

    def bad(body):
        r = proposer(body)
        p = json.loads(r["choices"][0]["message"]["content"])
        p["parameters"]["obstacle_height"] = 0.3
        r["choices"][0]["message"]["content"] = json.dumps(p)
        return r

    with pytest.raises(ValueError, match="domain"):
        x.run(root, fake_runner, bad, 1)
    assert not (root / "seed_641/afs/attempt_00002/robot_intent.json").exists()


def test_native_failure_does_not_require_contact(prepared):
    root, _ = prepared

    def fail(c, v, d):
        placement.save(d / "receipt.json", {"status": "VALID", "task_outcome": "FAIL"})
        placement.save(d / "measurement.json", {"status": "UNKNOWN", "contact": None})
        x.seal(d)

    out = x.run(root, fail, proposer, 1)["totals"]["afs"]
    assert out["fail"] == 1 and out["contact_fail"] == 0 and out["unknown_measurement"] == 1
    assert out["first_failure_attempt_by_seed"]["641"] == 1


def test_worker_seals_measurement_and_refuses_second_start(prepared, monkeypatch):
    root, design = prepared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import run_robot_arm_environment_search as cli

    d = root / "seed_641/afs/attempt_00000"
    d.mkdir(parents=True)
    v = x.candidate(design, x.uniform(design, 641, 0), 641, 0, "uniform bootstrap")
    placement.save(d / "candidate.json", v)
    placement.save(d / "robot_intent.json", v)
    monkeypatch.setattr(
        cli.obstacles, "run", lambda *a: {"status": "VALID", "task_outcome": "PASS", "steps": [1]}
    )
    assert cli.worker(d) == 0
    assert x.receipt(d, v)["task_outcome"] == "PASS"
    assert search.read(d / "measurement.json")["status"] == "UNKNOWN"
    with pytest.raises(FileExistsError):
        cli.worker(d)


def test_api_usage_unknown_not_zero(prepared):
    root, _ = prepared
    x.run(root, fake_runner, proposer, 8)

    def crash(*a):
        raise RuntimeError("timeout")

    with pytest.raises(RuntimeError):
        x.run(root, fake_runner, crash, 1)
    out = x.summary(root)["totals"]["afs"]
    assert out["afs_requests"] == 1 and out["unknown_usage_requests"] == 1


def test_all_ten_axes_bind_actual_scene(prepared):
    _, d = prepared
    p = {a: sum(v) / 2 for a, v in d["domain"].items()}
    c = x.candidate(d, p, 661, 0, "cpu")
    assert len(p) == 10 and set(p) == set(x.AXES)
    assert c["positions"] == {a: p[a] for a in placement.AXES}
    assert c["obstacles"][0]["size_m"] == [
        p["obstacle_width"],
        p["obstacle_depth"],
        p["obstacle_height"],
    ]
    assert c["obstacles"][0]["yaw_rad"] == p["obstacle_yaw"]
    context = json.loads(x.body(d, [])["messages"][-1]["content"][0]["text"])
    assert context["units"]["obstacle_yaw"] == "radians"
    assert context["shared_domain"] == d["domain"]


def test_position_domain_mismatch_refused(prepared):
    _, d = prepared
    d["domain"]["plate_x"] = [0.06, 0.09]
    with pytest.raises(ValueError, match="position domain"):
        x.validate(d)


def test_rotated_box_compiles_and_contacts():
    import math

    import mujoco
    import numpy as np

    from robot_arm import environment_obstacles as e

    xml = """<mujoco><worldbody><body name="table" pos="0 0 .875">
    <geom name="table_collision" type="box" size=".5 .6 .025"/></body>
    <body pos="0 0 1.2"><freejoint/><geom name="probe" type="sphere" size=".015" mass=".1"/>
    </body></worldbody></mujoco>"""
    item = {
        "id": "probe_box",
        "shape": "box",
        "xy_m": [0, 0],
        "size_m": [0.08, 0.04, 0.1],
        "yaw_rad": math.pi / 4,
    }
    model = mujoco.MjModel.from_xml_string(e.inject(xml, [item]))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    g = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "s2t_obstacle_probe_box_geom")
    assert np.allclose(
        data.geom_xmat[g].reshape(3, 3)[:2, :2], [[2**-0.5, -(2**-0.5)], [2**-0.5, 2**-0.5]]
    )
    for _ in range(500):
        mujoco.mj_step(model, data)
    assert data.qpos[2] > 1.0
    assert any(g in (int(c.geom1), int(c.geom2)) for c in data.contact[: data.ncon])


@pytest.mark.parametrize("angle", [True, float("nan"), float("inf"), 2])
def test_invalid_yaw_rejected(angle):
    from robot_arm import environment_obstacles as e

    with pytest.raises(ValueError):
        e.checked(
            [
                {
                    "id": "b",
                    "shape": "box",
                    "xy_m": [0, 0],
                    "size_m": [0.03, 0.03, 0.10],
                    "yaw_rad": angle,
                }
            ]
        )


def test_rotated_footprint_checks_table_corners():
    import math

    from robot_arm import environment_obstacles as e

    xml = (
        '<mujoco><worldbody><body name="table">'
        '<geom name="table_collision" type="box" size=".5 .6 .025"/>'
        "</body></worldbody></mujoco>"
    )
    with pytest.raises(ValueError, match="footprint"):
        e.inject(
            xml,
            [
                {
                    "id": "b",
                    "shape": "box",
                    "xy_m": [0.4, 0],
                    "size_m": [0.3, 0.3, 0.1],
                    "yaw_rad": math.pi / 4,
                }
            ],
        )


def test_new_adapter_leaves_legacy_obstacles_contract_intact():
    from robot_arm import environment_obstacles as e
    from robot_arm import obstacles

    item = {"id": "b", "shape": "box", "xy_m": [0, 0], "size_m": [0.03, 0.03, 0.1]}
    assert obstacles.checked([item]) == [item]
    with pytest.raises(ValueError):
        e.checked([item])
    with pytest.raises(ValueError):
        obstacles.checked([{**item, "yaw_rad": 0}])


def test_expansion_contains_previous_obstacle_domain():
    project = Path(__file__).resolve().parents[1]
    old = search.read(project / "config/robot_arm_obstacle_comparison.json")
    new = search.read(project / "config/robot_arm_environment_comparison.json")
    for axis, pair in old["domain"].items():
        assert new["domain"][axis][0] <= pair[0] < pair[1] <= new["domain"][axis][1]
    p = {a: sum(v) / 2 for a, v in new["domain"].items()}
    p.update(old["positions"], obstacle_width=0.05, obstacle_depth=0.06, obstacle_yaw=0)
    x.checked(new, p)
