"""CPU-only isolation, shared-domain, durable-resume and contact/outcome contracts."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import placement, search
from robot_arm import staged_search as x


@pytest.fixture
def prepared(tmp_path):
    design = search.read(
        Path(__file__).resolve().parents[1] / "config/robot_arm_staged_comparison.json"
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
    assert out["totals"]["afs"]["unique_environment_settings"] == 7
    assert out["totals"]["afs"]["repeated_environment_settings"] == 5
    assert len(seen) == 24 and len(contexts) == 8
    assert all(t["fail"] == 0 and t["contact_pass"] == 12 for t in out["totals"].values())
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
    p["block_height"] = value
    with pytest.raises(ValueError):
        x.checked(d, p)


def test_uniform_shared_domain(prepared):
    _, d = prepared
    for seed in d["experiment"]["seeds"]:
        for i in range(4):
            p = x.uniform(d, seed, i)
            assert p == x.uniform(d, seed, i)
            assert x.checked(d, p, i) == p


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
    v["parameters"]["block_height"] = 0.10
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
        p["parameters"]["block_height"] = 0.3
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
    import run_robot_arm_staged_search as cli

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


def test_stages_are_balanced_and_boxes_have_true_clear_gap(prepared):
    import math

    _, d = prepared
    stages = []
    for i in range(6):
        p = {a: sum(v) / 2 for a, v in x.domain(d, i).items()}
        c = x.candidate(d, p, 701, i, "geometry")
        stages.append(c["stage"])
        assert len(c["obstacles"]) == 2
        a, b = c["obstacles"]
        separation = math.dist(a["xy_m"], b["xy_m"])
        assert separation - a["size_m"][1] == pytest.approx(p["gap"])
        assert a["yaw_rad"] == b["yaw_rad"]
    assert all(stages.count(stage) == 2 for stage in x.STAGES)


def test_placement_progress_cannot_leak_into_approach(prepared):
    _, d = prepared
    p = {a: sum(v) / 2 for a, v in x.domain(d, 2).items()}
    x.checked(d, p, 2)
    with pytest.raises(ValueError, match="domain"):
        x.checked(d, p, 0)


def test_afs_receives_current_stage_and_motion_feedback(prepared):
    _, d = prepared
    body = x.body(
        d, [{"measurement": {"motion_observations": {"pattern": "little_object_motion"}}}], 2
    )
    context = json.loads(body["messages"][-1]["content"][0]["text"])
    assert context["stage"] == "placement"
    assert context["shared_domain"] == d["domains"]["placement"]
    assert (
        context["history"][0]["measurement"]["motion_observations"]["pattern"]
        == "little_object_motion"
    )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("stationary", "little_object_motion"),
        ("move", "object_moved_native_task_incomplete"),
        ("near", "object_near_goal_native_task_incomplete"),
        ("pass", "native_task_completed"),
    ],
)
def test_motion_descriptions_do_not_replace_native_verdict(tmp_path, kind, expected):
    from robot_arm import phase_measure

    rows = []
    for i in range(301):
        point = [0, 0, 0.9]
        if i > 110 and kind == "move":
            point = [0.08, 0, 1.0]
        if i > 110 and kind == "near":
            point = [0.18, 0.20, 1.0]
        rows.append(
            {
                "time_s": i * 0.01,
                "dt_s": 0.01,
                "table_surface_z_m": 0.9,
                "bowl_xyz_m": point,
                "plate_xyz_m": [0.2, 0.2, 0.9],
                "eef_xyz_m": [0, 0, 1.1],
                "contacts": [],
            }
        )
    (tmp_path / "physics.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    receipt = {
        "status": "VALID",
        "task_outcome": "PASS" if kind == "pass" else "FAIL",
        "steps": [60],
    }
    original = dict(receipt)
    m = phase_measure.case_measure(tmp_path, receipt)
    assert m["motion_observations"]["pattern"] == expected
    assert receipt == original and m["motion_observations"]["cause"] == "UNCONFIRMED"


def test_partial_motion_is_unknown(tmp_path):
    from robot_arm import phase_measure

    m = phase_measure.case_measure(tmp_path, {"status": "INCONCLUSIVE", "task_outcome": None})
    assert m["motion_observations"] == {"status": "UNKNOWN", "pattern": None}


def test_rechecks_and_observation_patterns_are_not_new_failures(prepared):
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

    result = x.run(root, fail, proposer, 24)
    a = result["totals"]["afs"]
    assert a["fail"] == 12 and a["unique_failing_environment_settings"] == 7
    assert a["recheck_failures"] == 5
    assert a["failure_motion_patterns"] == {"little_object_motion": 12}
    assert all(v == {"valid": 4, "pass": 0, "fail": 4} for v in a["by_layout_stage"].values())
