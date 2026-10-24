"""Matched budgets, isolated evidence, durable intents and task-specific parameters."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from robot_arm import placement, search  # noqa: E402
from robot_arm import task_comparison as x  # noqa: E402
from robot_arm import task_environments as envs  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "task_cli", PROJECT / "tools/run_robot_arm_task_comparisons.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def prepared(root, design):
    root.mkdir(parents=True)
    placement.save(
        root / "manifest.json", {"design": design, "source_hashes": {}, "model_hashes": {}}
    )
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json"))
    return root


@pytest.fixture(params=["object", "goal"])
def campaign(tmp_path, request):
    d = cli.config(cli.DEFAULT)["tasks"][request.param][0]
    return prepared(tmp_path / "set", d), d


def fake_runner(d, v, folder):
    adaptive = folder.parent.name == "afs" and int(folder.name[-5:]) >= 2
    placement.save(
        folder / "receipt.json",
        {
            "status": "VALID",
            "task_outcome": "FAIL" if adaptive else "PASS",
            "steps": [10],
        },
    )
    placement.save(
        folder / "measurement.json",
        {
            "status": "COMPLETE",
            "pattern": "mock",
            "contact_seconds": {"robot_obstacle": 0.1},
        },
    )
    placement.save(folder / "initial_state.json", {"test_double": True})
    x.seal(folder)


def proposer(body):
    ctx = json.loads(body["messages"][-1]["content"][0]["text"])
    p = {a: sum(v) / 2 for a, v in ctx["shared_domain"].items()}
    return {
        "model": "openai/gpt-6-luna-pro",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"parameters": p, "hypothesis": "mock"}),
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_full_paired_run_history_budget_and_no_replay(campaign):
    root, d = campaign
    calls, contexts = [], []

    def run(design, v, folder):
        calls.append(folder)
        fake_runner(design, v, folder)

    def propose(body):
        ctx = json.loads(body["messages"][-1]["content"][0]["text"])
        past = ctx["own_seed_afs_history"]
        assert len(past) in (2, 3)
        assert all("/afs/" in r["evidence_id"] for r in past)
        assert len({r["evidence_id"].split("/")[0] for r in past}) == 1
        assert all(r["candidate"]["task"] == d["task"] for r in past)
        contexts.append(ctx)
        return proposer(body)

    result = x.run(root, run, propose)
    assert result["complete"] and len(calls) == 24 and len(contexts) == 6
    assert result["totals"]["afs"]["fail"] == 6
    assert result["totals"]["afs"]["known_input_tokens"] == 60
    assert result["totals"]["random"]["fail"] == 0
    assert result["difference_percentage_points"] == 50
    assert result["totals"]["afs"]["unique_failing_settings"] == 1
    assert result["totals"]["afs"]["recheck_failures"] == 5
    for seed in d["seeds"]:
        for index in range(2):
            assert search.read(
                root / f"seed_{seed}/afs/attempt_{index:05d}/candidate.json"
            ) == search.read(root / f"seed_{seed}/random/attempt_{index:05d}/candidate.json")
    assert (
        x.run(root, lambda *a: pytest.fail("replayed robot"), lambda *a: pytest.fail("resent API"))
        == result
    )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -999, 999])
def test_bad_parameters_rejected(campaign, value):
    _, d = campaign
    p = x.uniform(d, d["seeds"][0], 0)
    p["box_height"] = value
    with pytest.raises(ValueError):
        x.checked(d, p)


def test_pending_api_never_resends(campaign):
    root, _ = campaign
    x.run(root, fake_runner, proposer, 12)

    def failed(body):
        raise RuntimeError("ambiguous transport")

    with pytest.raises(RuntimeError, match="ambiguous transport"):
        x.run(root, fake_runner, failed)
    with pytest.raises(RuntimeError, match="pending API"):
        x.run(root, lambda *a: pytest.fail("robot replay"), lambda *a: pytest.fail("API resend"))
    assert x.summary(root)["totals"]["afs"]["unknown_usage_requests"] == 1


def test_excluded_slot_no_replacement(campaign):
    root, _ = campaign

    def excluded(d, v, folder):
        placement.save(folder / "receipt.json", {"status": "INCONCLUSIVE", "task_outcome": None})
        placement.save(folder / "measurement.json", {"status": "UNKNOWN"})
        x.seal(folder)

    with pytest.raises(RuntimeError, match="exclusion"):
        x.run(root, excluded, proposer)
    assert x.summary(root)["totals"]["afs"]["excluded"] == 1
    assert x.summary(root)["totals"]["afs"]["fail"] == 0
    with pytest.raises(RuntimeError, match="excluded slot"):
        x.run(root, lambda *a: pytest.fail("replaced exclusion"), proposer)


def test_pending_robot_never_replays(campaign):
    root, _ = campaign

    def interrupted(*args):
        raise RuntimeError("stopped")

    with pytest.raises(RuntimeError, match="stopped"):
        x.run(root, interrupted, proposer)
    with pytest.raises(RuntimeError, match="pending robot"):
        x.run(root, lambda *a: pytest.fail("robot replay"), proposer)


def test_task_and_checkpoint_must_match(campaign):
    _, d = campaign
    changed = copy.deepcopy(d)
    changed["robot"]["suite"] = "libero_spatial"
    with pytest.raises(ValueError, match="task/checkpoint"):
        x.validate(changed)


def test_initial_only_xml_leaves_robot_and_success_unchanged(campaign):
    _, d = campaign
    xml = '<mujoco><worldbody><body name="robot0"><joint range="-1 1"/></body>'
    if d["task"] == "object":
        xml += '<body name="butter_1_main"><geom density="100" friction="0.9 0.3 0.1"/></body>'
    else:
        xml += (
            '<body><joint name="wooden_cabinet_1_middle_level" '
            'range="-0.16 0.01" damping="50"/></body>'
        )
    xml += "</worldbody></mujoco>"
    p = {a: sum(v) / 2 for a, v in d["domain"].items()}
    import xml.etree.ElementTree as ET

    before, after = ET.fromstring(xml), ET.fromstring(envs.inject(xml, d["task"], p))
    assert ET.tostring(before.find('.//body[@name="robot0"]')) == ET.tostring(
        after.find('.//body[@name="robot0"]')
    )
    if d["task"] == "goal":
        joint = after.find('.//joint[@name="wooden_cabinet_1_middle_level"]')
        assert joint.get("range") == "-0.16 0.01"
        assert float(joint.get("damping")) == 50 * p["drawer_damping_scale"]


def test_three_set_aggregation_waits_for_complete_task(tmp_path, capsys):
    c = cli.config(cli.DEFAULT)
    rows = []
    for task, ds in c["tasks"].items():
        for number, d in enumerate(ds, 1):
            child = prepared(tmp_path / task / f"set_{number}", d)
            rows.append(
                {
                    "task": task,
                    "set": number,
                    "directory": str(child.relative_to(tmp_path)),
                    "manifest_sha256": search.sha(child / "manifest.json"),
                }
            )
    placement.save(tmp_path / "bundle.json", {"config": c, "plan": cli.plan(c), "sets": rows})
    (tmp_path / "bundle.sha256").write_text(search.sha(tmp_path / "bundle.json"))
    result = cli.report(tmp_path)
    assert not result["complete"]
    assert all(t["aggregate"] is None for t in result["tasks"].values())
    for row in rows:
        x.run(tmp_path / row["directory"], fake_runner, proposer)
    result = cli.report(tmp_path)
    assert result["complete"]
    for t in result["tasks"].values():
        assert t["aggregate"]["afs"]["mean_percent"] == 50
        assert t["aggregate"]["afs"]["sample_sd_percentage_points"] == 0
        assert t["aggregate"]["paired_difference"]["mean_percentage_points"] == 50


def test_incomplete_physics_is_unknown(tmp_path):
    placement.save(tmp_path / "receipt.json", {"status": "VALID", "task_outcome": "FAIL"})
    assert envs.measure(tmp_path, {"status": "VALID"}, "goal")["status"] == "UNKNOWN"


def test_native_cpu_environment_with_policy_and_camera_doubles(tmp_path):
    interpreter = PROJECT / "experiments/robot_arm_libero/.venv-arm/bin/python"
    if not interpreter.exists():
        pytest.skip("native LIBERO interpreter unavailable")
    result = subprocess.run(
        [str(interpreter), str(PROJECT / "tests/helpers/task_native_cpu_probe.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CPU_PROBE_OK object" in result.stdout and "CPU_PROBE_OK goal" in result.stdout
