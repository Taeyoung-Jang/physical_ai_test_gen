"""CPU-only independent histories, identical domains and across-set sample SD."""

import copy
import sys
from pathlib import Path

import pytest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "tools"),
    str(Path(__file__).resolve().parents[1] / "src"),
]
import run_robot_arm_search_repetitions as batch  # noqa: E402

from robot_arm import search  # noqa: E402


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    design = search.read(batch.BASE)
    design["experiment"]["robot"]["model_path"] = str(tmp_path / "model")
    Path(design["experiment"]["robot"]["model_path"]).mkdir()
    config = tmp_path / "base.json"
    config.write_text(__import__("json").dumps(design))
    monkeypatch.setattr(batch, "BASE", config)
    monkeypatch.setattr(batch.cli, "sources", lambda c: [])
    root = tmp_path / "batch"
    batch.prepare(root, [551, 552, 553])
    return root


def test_three_new_sets_same_budget_empty_histories(prepared):
    root = prepared
    plan = batch.plan_for(root)
    seeds = [s for row in plan["sets"] for s in row["search_seeds"]]
    assert len(set(seeds)) == 9 and not set(seeds).intersection([727, 733, 739])
    assert plan["robot_attempt_cap"] == 72 and plan["afs_request_cap"] == 18
    result = batch.summarize(root)
    assert not result["complete"] and result["aggregate"] is None
    for row in result["sets"]:
        assert all(
            t["attempts"] == t["afs_requests"] == 0 for t in row["summary"]["totals"].values()
        )
        manifest = search.read(root / row["directory"] / "manifest.json")
        assert manifest["config"]["per_arm"] == 4
        assert manifest["config"]["bootstrap"] == 2
        assert "inherited_artifacts" not in manifest
    with pytest.raises(FileExistsError):
        batch.prepare(root, [551, 552, 553])


def test_aggregate_is_three_set_sample_sd_not_episode_sd(prepared, monkeypatch):
    def summary(child):
        i = int(child.name[-1]) - 1
        return {
            "attempt_budget_complete": True,
            "totals": {"afs": {"fail": [6, 8, 4][i]}, "random": {"fail": [2, 3, 1][i]}},
        }

    monkeypatch.setattr(batch.experiment, "summary", summary)
    result = batch.summarize(prepared)
    a = result["aggregate"]
    assert a["afs"]["mean_percent"] == pytest.approx(50)
    assert a["afs"]["sample_sd_percentage_points"] == pytest.approx(100 / 6)
    assert a["random"]["mean_percent"] == pytest.approx(100 / 6)
    assert a["random"]["sample_sd_percentage_points"] == pytest.approx(100 / 12)
    assert a["paired_difference"]["mean_percentage_points"] == pytest.approx(100 / 3)
    assert not result["statistical_superiority_established"]

    def incomplete(child):
        row = summary(child)
        row["attempt_budget_complete"] = child.name != "set_3"
        return row

    monkeypatch.setattr(batch.experiment, "summary", incomplete)
    assert batch.summarize(prepared)["aggregate"] is None


def test_manifest_and_condition_drift_stops(prepared):
    child = prepared / "set_2/manifest.json"
    child.write_text(child.read_text() + "\n")
    with pytest.raises(ValueError, match="manifest changed"):
        batch.summarize(prepared)


def test_failed_set_not_automatically_retried_or_replaced(prepared, monkeypatch):
    import robot_arm.openrouter as provider

    monkeypatch.setattr(provider, "require_key", lambda: None)
    monkeypatch.setattr(batch.experiment, "verify", lambda root: None)
    monkeypatch.setattr(batch, "write_report", lambda root: {"complete": False})
    calls = []

    class Child:
        def __init__(self, args, **kwargs):
            calls.append(copy.deepcopy(args))

        def wait(self):
            return 1

    monkeypatch.setattr(batch.subprocess, "Popen", Child)
    with pytest.raises(RuntimeError, match="set 1 stopped"):
        batch.execute(prepared)
    assert len(calls) == 1
    assert "--max-new-attempts" in calls[0] and calls[0][-1] == "24"
