"""CPU-only isolation, shared-domain, durable-resume and contact/outcome contracts."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import free_pair_search as x
from robot_arm import placement, search


@pytest.fixture
def prepared(tmp_path):
    design = search.read(
        Path(__file__).resolve().parents[1] / "config/robot_arm_free_pair_comparison.json"
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
    p["box1_height"] = value
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
    v["parameters"]["box1_height"] = 0.10
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
        p["parameters"]["box1_height"] = 0.3
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
    import run_robot_arm_free_pair_search as cli

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


def test_sixteen_axes_are_independently_applied(prepared):
    _, d = prepared
    p = {a: sum(v) / 2 for a, v in d["domain"].items()}
    p["box1_yaw"] = 0.6
    p["box2_yaw"] = -0.7
    p["box1_height"] = 0.10
    p["box2_height"] = 0.19
    c = x.candidate(d, p, 727, 0, "test")
    assert len(x.AXES) == 16 and len(c["obstacles"]) == 2
    for i, item in enumerate(c["obstacles"], 1):
        assert item["xy_m"] == [p[f"box{i}_x"], p[f"box{i}_y"]]
        assert item["size_m"] == [p[f"box{i}_width"], p[f"box{i}_depth"], p[f"box{i}_height"]]
        assert item["yaw_rad"] == p[f"box{i}_yaw"]
    assert c["obstacles"][0]["yaw_rad"] != c["obstacles"][1]["yaw_rad"]
    assert c["positions"] == {a: p[a] for a in placement.AXES}
    ctx = json.loads(x.body(d, [])["messages"][-1]["content"][0]["text"])
    assert ctx["shared_domain"] == d["domain"]
    assert ctx["units"]["box2_yaw"] == "radians"


def test_initial_static_overlap_rejected_and_touch_allowed():
    from robot_arm import free_pair_obstacles as e

    a = {"id": "a", "shape": "box", "xy_m": [0, 0], "size_m": [0.08, 0.04, 0.1], "yaw_rad": 0}
    b = {**a, "id": "b", "xy_m": [0.04, 0]}
    assert e.overlap_pairs([a, b]) == [["a", "b"]]
    xml = (
        '<mujoco><worldbody><body name="table">'
        '<geom name="table_collision" type="box" size=".5 .6 .025"/>'
        "</body></worldbody></mujoco>"
    )
    with pytest.raises(ValueError, match="overlap"):
        e.inject(xml, [a, b])
    b["xy_m"] = [0.08, 0]
    assert e.overlap_pairs([a, b]) == []


def test_rotated_separating_axis_does_not_reject_aabb_overlap():
    import math

    from robot_arm import free_pair_obstacles as e

    a = {
        "id": "a",
        "shape": "box",
        "xy_m": [0, 0],
        "size_m": [0.12, 0.02, 0.1],
        "yaw_rad": math.pi / 4,
    }
    b = {**a, "id": "b", "xy_m": [0, 0.04]}
    assert e.overlap_pairs([a, b]) == []
    b["xy_m"] = [0, 0.01]
    assert e.overlap_pairs([a, b]) == [["a", "b"]]


def test_two_distinct_rotations_reach_real_mujoco():
    import math

    import mujoco
    import numpy as np

    from robot_arm import free_pair_obstacles as e

    xml = (
        '<mujoco><worldbody><body name="table">'
        '<geom name="table_collision" type="box" size=".5 .6 .025"/>'
        "</body></worldbody></mujoco>"
    )
    items = [
        {"id": strid, "shape": "box", "xy_m": xy, "size_m": [0.06, 0.03, 0.1], "yaw_rad": angle}
        for strid, xy, angle in [("a", [-0.12, 0.1], 0.6), ("b", [-0.1, 0.27], -0.7)]
    ]
    m = mujoco.MjModel.from_xml_string(e.inject(xml, items))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    for item in items:
        g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, e.PREFIX + item["id"] + "_geom")
        angle = item["yaw_rad"]
        assert np.allclose(
            d.geom_xmat[g].reshape(3, 3)[:2, :2],
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]],
        )


def test_motion_patterns_and_rechecks_count_separately(prepared):
    root, _ = prepared

    def fail(c, v, d):
        placement.save(d / "receipt.json", {"status": "VALID", "task_outcome": "FAIL"})
        placement.save(
            d / "measurement.json",
            {
                "status": "COMPLETE",
                "contact": True,
                "motion_observations": {"status": "COMPLETE", "pattern": "little_object_motion"},
            },
        )
        x.seal(d)

    out = x.run(root, fail, proposer, 24)["totals"]["afs"]
    assert out["fail"] == 8 and out["unique_failing_environment_settings"] == 5
    assert out["recheck_failures"] == 3
    assert out["failure_motion_patterns"] == {"little_object_motion": 8}


def test_cancelled_construction_continues_without_replaying_slot(prepared, monkeypatch, tmp_path):
    root, design = prepared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import recover_cancelled_free_pair as recovery

    seed = design["experiment"]["seeds"][0]
    relative = f"seed_{seed}/afs/attempt_00000"
    d = root / relative
    d.mkdir(parents=True)
    value = x.candidate(design, x.uniform(design, seed, 0), seed, 0, "uniform bootstrap")
    placement.save(d / "candidate.json", value)
    placement.save(d / "robot_intent.json", value)
    placement.save(d / "manifest.json", {"mode": "manual"})
    placement.save(d / "worker_started.json", {"pid": 99999999})
    (d / "run.log").write_text("create_gr00t_sim_policy(\nimport gr00t.model\nKeyboardInterrupt\n")
    before = {str(p): search.sha(p) for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(recovery.cli, "sources", lambda c: [])
    target = tmp_path / "continued"
    result = recovery.prepare(root, target)
    assert result["new_attempt_cap"] == 15
    seen = []

    def runner(c, v, d):
        seen.append(str(d.relative_to(target)))
        fake_runner(c, v, d)

    out = x.run(target, runner, proposer, 24)
    assert len(seen) == 15 and relative not in seen
    assert out["attempt_budget_complete"] and not out["equal_valid_budget_complete"]
    assert out["totals"]["afs"]["excluded"] == 1 and out["totals"]["afs"]["fail"] == 0
    assert all(search.sha(p) == h for p, h in before.items())
    assert (
        x.run(target, lambda *a: pytest.fail("rerun"), lambda *a: pytest.fail("API resend"), 24)
        == out
    )
    with pytest.raises(FileExistsError):
        recovery.prepare(root, target)


def test_cancellation_with_possible_rollout_is_not_auto_recovered(prepared, tmp_path):
    root, design = prepared
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import recover_cancelled_free_pair as recovery

    seed = design["experiment"]["seeds"][0]
    d = root / f"seed_{seed}/afs/attempt_00000"
    d.mkdir(parents=True)
    for name in ["candidate.json", "manifest.json", "robot_intent.json", "worker_started.json"]:
        placement.save(d / name, {})
    (d / "run.log").write_text("KeyboardInterrupt")
    (d / "trace.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="rollout may have started"):
        recovery.prepare(root, tmp_path / "unsafe")
    assert not (tmp_path / "unsafe").exists()


def test_one_command_launcher_uses_continuation_only(tmp_path):
    import shutil
    import subprocess

    project = Path(__file__).resolve().parents[1]
    (tmp_path / "tools").mkdir()
    script = tmp_path / "tools/continue_robot_arm_free_pair.sh"
    shutil.copyfile(project / "tools/continue_robot_arm_free_pair.sh", script)
    executable = tmp_path / ".venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > called_args.txt\n')
    executable.chmod(0o755)
    subprocess.run(["bash", str(script)], cwd=tmp_path.parent, check=True)
    assert (tmp_path / "called_args.txt").read_text().splitlines() == [
        "tools/run_robot_arm_free_pair_search.py",
        "run",
        "--live",
        "--output",
        "experiments/robot_arm_libero/free_pair_continuation_v5",
        "--max-new-attempts",
        "23",
    ]
