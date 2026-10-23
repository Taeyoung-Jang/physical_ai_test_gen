"""CPU-only isolation, shared-domain, durable-resume and contact/outcome contracts."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import obstacle_search as x
from robot_arm import placement, search


@pytest.fixture
def prepared(tmp_path):
    design = search.read(
        Path(__file__).resolve().parents[1] / "config/robot_arm_obstacle_comparison.json"
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
    values = {a: sum(v) / 2 for a, v in context["shared_domain_m"].items()}
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
    import run_robot_arm_obstacle_search as cli

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


def test_recovery_preserves_excluded_slot_without_replacement(prepared, monkeypatch, tmp_path):
    root, design = prepared
    design["experiment"]["seeds"] = [641, 647, 653]
    m = search.freeze(design["experiment"], [])
    m.update(mode=x.VERSION, design=design)
    (root / "manifest.json").write_text(json.dumps(m))
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json"))
    slots = [
        (s, i, method) for i in range(2) for s in [641, 647, 653] for method in ["afs", "random"]
    ][:10]
    for s, i, method in slots:
        d = root / f"seed_{s}" / method / f"attempt_{i:05d}"
        d.mkdir(parents=True)
        v = x.candidate(design, x.uniform(design, s, i), s, i, "uniform bootstrap")
        placement.save(d / "candidate.json", v)
        placement.save(d / "robot_intent.json", v)
        if (s, i, method) == (647, 1, "random"):
            placement.save(d / "manifest.json", {"mode": "manual"})
            (d / "run.log").write_text(
                "return worker(root)\nValueError: frozen file changed: "
                + str(Path(__file__).resolve().parents[1] / "src/llm_afs/provider.py")
            )
        else:
            fake_runner({}, v, d)
    before = {str(p): search.sha(p) for p in root.rglob("*") if p.is_file()}
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import recover_robot_arm_obstacle_search as recovery

    monkeypatch.setattr(recovery.cli, "sources", lambda c: [])
    target = tmp_path / "recovered"
    info = recovery.recover(root, target)
    assert info["new_attempt_cap"] == 14
    assert all(search.sha(p) == h for p, h in before.items())
    seen = []

    def runner(c, v, d):
        seen.append(str(d.relative_to(target)))
        fake_runner(c, v, d)

    out = x.run(target, runner, proposer, 14)
    assert len(seen) == 14 and recovery.BLOCKED not in seen
    assert out["attempt_budget_complete"] and not out["equal_valid_budget_complete"]
    assert out["relative_fdr_gain"] is None
    assert out["totals"]["afs"]["valid"] == 12
    assert out["totals"]["random"]["valid"] == 11 and out["totals"]["random"]["excluded"] == 1
    assert out["totals"]["afs"]["afs_requests"] == 6
    assert (
        x.run(target, lambda *a: pytest.fail("rerun"), lambda *a: pytest.fail("resend"), 14) == out
    )
    with pytest.raises(FileExistsError):
        recovery.recover(root, target)


def test_unacknowledged_exclusion_still_stops(prepared):
    root, _ = prepared

    def excluded(c, v, d):
        placement.save(
            d / "receipt.json",
            {
                "status": "INCONCLUSIVE",
                "task_outcome": None,
                "reason": "preserved_pre_worker_source_drift",
            },
        )
        placement.save(d / "measurement.json", {"status": "UNKNOWN"})
        x.seal(d)

    with pytest.raises(RuntimeError):
        x.run(root, excluded, proposer, 1)
    with pytest.raises(RuntimeError, match="excluded"):
        x.run(root, fake_runner, proposer, 1)
