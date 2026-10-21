"""Random-only preparation and execution against CPU fixture archives."""

import copy
import json
from pathlib import Path

import pytest

from failure_client.experiments.paired_discovery import (
    PairedDesign,
    PairedDiscovery,
    paired_plan,
)
from failure_client.methods.behavior_feedback import uniform_scene

from .test_afs_contrast import Robot, fingerprint
from .test_cause_review import cause_engine
from .test_independent_discovery import OutcomeRobot


def config():
    return json.loads(
        (Path(__file__).parents[2] / "config/random_environment_luna.json").read_text()
    )


def setup(tmp_path, *, robot=None):
    control = cause_engine(tmp_path)
    plan = paired_plan(
        [r["source"]["path"] for r in control.plan["history"]],
        PairedDesign.model_validate(config()),
        fingerprint_fn=fingerprint,
    )
    root = PairedDiscovery.create(tmp_path / "random", plan, fingerprint_fn=fingerprint)
    runner = robot or OutcomeRobot("FAIL")

    def forbidden(*args, **kwargs):
        pytest.fail("Random attempted an AFS call")

    return (
        PairedDiscovery(root, runner=runner, proposer=forbidden, fingerprint_fn=fingerprint),
        runner,
        control,
    )


def test_offline_zero_calls_preview_is_seeded_full_domain_and_not_bootstrap(tmp_path):
    e, r, control = setup(tmp_path)
    s = e.summary()
    assert not r.calls and s["new_attempts"] == s["afs_request_upper_bound"] == 0
    assert s["robot_api_call_upper_bound"] == 120
    schedule = e.random_schedule()
    assert len(schedule) == 12
    assert len({json.dumps(x["parameters"], sort_keys=True) for x in schedule}) == 12
    for arm in e.arms():
        assert arm.plan["method"] == "random" and arm.plan["history"] == []
        candidate, ctx = arm._selection()
        assert ctx is None and candidate["stage"] == "discovery"
        assert candidate["parameters"] == uniform_scene(
            arm.plan["seed"], "paired-random-v1", 0, schema=arm.cfg.scene_schema
        )
        assert set(candidate["parameters"]) == set(e.manifest["domain_axes"])
        assert arm.summary()["afs_requests_remaining"] == 0
    assert control.plan["history"]  # verified settings controls, never evaluation memory
    for values in s["environment_distribution"]["planned"].values():
        assert sum(values["third_bin_counts"]) == 12
    report = e.report()
    assert json.loads((report.parent / "planned_random_scenes.json").read_text()) == schedule
    assert not r.calls


def test_batch_twelve_executes_once_without_afs_or_gain_and_stops_at_budget(tmp_path):
    e, r, _ = setup(tmp_path)
    s = e.run(live=True, max_new_attempts=12)
    assert s["status"] == "COMPLETE" and len(r.calls) == 12
    assert s["afs_requests_attempted"] == s["afs_request_upper_bound"] == 0
    assert s["comparison"]["status"] == "not_requested_random_only"
    assert s["comparison"]["relative_gain"] is None
    assert not s["fixed_budget_observation_available"]
    assert not s["statistical_superiority_established"]
    for arm in s["arms"]:
        assert arm["valid"] == arm["attempted"] == arm["fail"] == 4
        assert arm["afs_requests_attempted"] == 0
    for name in ("system_twelve", "original_six"):
        assert s["metrics"][name]["input_records"] == 12
        assert {g["method"] for g in s["metrics"][name]["groups"]} == {"random"}
        assert {g["seed"] for g in s["metrics"][name]["groups"]} == {29, 43, 71}
    assert s["environment_distribution"]["random_attempt_intents"] == 12
    for values in s["environment_distribution"]["attempted"].values():
        assert sum(values["third_bin_counts"]) == 12
    e.run(live=True, max_new_attempts=12)
    assert len(r.calls) == 12


def test_excluded_random_is_not_replayed_or_silently_replaced(tmp_path):
    e, r, _ = setup(tmp_path, robot=Robot(excluded=True))
    first = e.run(live=True, max_new_attempts=12)
    assert first["status"] == "NEEDS_ATTENTION" and len(r.calls) == 1
    e.run(live=True, max_new_attempts=12)
    assert len(r.calls) == 1
    r.excluded = False
    end = e.run(live=True, max_new_attempts=12, continue_after_exclusion=True)
    assert len(r.calls) == 4 and len({json.dumps(x, sort_keys=True) for x in r.calls}) == 4
    assert end["status"] == "TARGET_NOT_REACHED"
    assert [x["attempted"] for x in end["arms"]] == [4, 0, 0]


def test_random_live_guard_and_proposal_branch_are_closed(tmp_path):
    e, r, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="live"):
        e.run()
    with pytest.raises(ValueError, match="unplanned"):
        e.arm(29, "afs")
    with pytest.raises(ValueError, match="never dispatch"):
        e.arm(29, "random")._proposal({})
    assert not r.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("methods", ["afs", "random"]),
        ("afs_requests_per_seed", 1),
        ("cold_start_per_arm", 2),
        ("seeds", [29, 29]),
    ],
)
def test_random_design_rejects_hidden_afs_bootstrap_or_selected_seed(field, value):
    data = copy.deepcopy(config())
    data[field] = value
    with pytest.raises(ValueError):
        PairedDesign.model_validate(data)
