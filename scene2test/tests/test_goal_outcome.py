import io
import json

import pytest

from robot_vlm.behavior_events import BehaviorEvents
from robot_vlm.task_outcome import GoalEvaluator, digest, task_contract


def evaluator():
    return GoalEvaluator(task_contract([7.0, 0.0], 10, None))


def test_goal_dwell_resets_and_has_no_posture_or_contact_condition():
    e = evaluator()
    assert not e.observe(0, [7, 0])
    assert not e.observe(0.9, [6, 0])
    assert not e.observe(1, [7, 0])
    assert e.observe(2, [7, 0])
    assert e.result("GOAL_REACHED", True)["task_outcome"] == "PASS"
    assert e.result("SKILL_RELEASE_FAILURE", True)["task_outcome"] == "PASS"
    assert e.result("NUMERICAL_ERROR", False)["task_outcome"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "reason", ["POLICY_STOP", "BUDGET_EXHAUSTED", "INFERENCE_SIM_BUDGET", "SIMULATION_BUDGET"]
)
def test_valid_noncompletion_is_failure(reason):
    r = evaluator().result(reason, True)
    assert r["task_outcome"] == "FAIL" and r["goal_reached"] is False


@pytest.mark.parametrize("reason", ["FALL", "FORBIDDEN_CONTACT", "response_deadline", "CANCELLED"])
def test_truncated_episode_has_no_goal_label(reason):
    r = evaluator().result(reason, True)
    assert r["task_outcome"] == "INCONCLUSIVE" and r["goal_reached"] is None


def test_budget_and_profile_change_contract_digest():
    c = task_contract([7.0, 0.0], 10, None)
    assert digest(c) != digest(task_contract([7.0, 0.0], 11, None))
    assert digest(c) != digest(task_contract([7.0, 0.0], 10, 120))
    assert digest(c) != digest(task_contract([7.0, 0.0], 10, None, "legacy_guarded"))


def test_event_episodes_force_integral_recovery_and_truncation():
    stream = io.StringIO()
    events = BehaviorEvents(stream)
    conditions = {
        "hand_box": {"kind": "contact", "peak_normal_force_n": 5.0, "sum_normal_force_n": 8.0},
        "fall": {"kind": "fall"},
    }
    events.update(conditions, 0.1, "push_handoff", 0.1)
    snapshot = events.observation()
    events.update(conditions, 0.2, "push_handoff", 0.1)
    assert snapshot["active"][0]["normal_impulse_ns"] == pytest.approx(0.8)
    events.update({}, 0.3, "observe", 0.1)
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    contact_end = next(r for r in rows if r["event"] == "contact_end")
    assert contact_end["normal_impulse_ns"] == pytest.approx(1.6)
    assert contact_end["sampled_duration_s"] == pytest.approx(0.2)
    assert events.summary()["counts"]["contact_start"] == 1
    assert events.summary()["counts"]["upright_recovered"] == 1
    events.update({"fall": {"kind": "fall"}}, 0.4, "observe", 0.1)
    events.close(0.5, "observe")
    assert events.summary()["counts"]["upright_recovered"] == 1
