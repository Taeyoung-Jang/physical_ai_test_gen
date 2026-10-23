"""Flex opt-in wiring only; no network, GPU or paid model calls."""

import json

import httpx
import pytest

from failure_client.experiments.behavior_regression import replay_plan
from failure_client.experiments.local_goal_adapter import command
from failure_client.experiments.research_protocol import CampaignConfig
from failure_client.methods.autonomous_feedback import SearchBudget
from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.goal_policy import GoalPolicy
from robot_vlm.push_policy import PushPolicy

from .test_afs_autonomous import Proposer, reload, setup
from .test_afs_contrast import source


@pytest.mark.parametrize("policy_type", [GoalPolicy, PushPolicy])
@pytest.mark.parametrize("requested_tier", ["flex", "default"])
def test_robot_opt_in_body(policy_type, monkeypatch, requested_tier):
    monkeypatch.setattr(
        "robot_vlm.goal_policy.camera_request",
        lambda *a, **k: {
            "model": k["model"],
            "text": {"format": {}},
            "input": [{"content": [{"text": "{}"}]}],
        },
    )

    # Test the shared request builder before push-specific context augmentation.
    class Observation:
        yaw_rad = 0.0

        def model_dump(self):
            return {}

    policy = policy_type(model="gpt-6.1-sol", service_tier=requested_tier)
    body = GoalPolicy.body(policy, Observation(), b"unused")
    assert body["model"] == "gpt-6.1-sol"
    assert body["service_tier"] == requested_tier
    assert "max_output_tokens" not in body
    assert "service_tier" not in GoalPolicy.body(GoalPolicy(), Observation(), b"unused")


@pytest.mark.parametrize("tier", ["flex", "default", None])
@pytest.mark.parametrize("requested_tier", ["flex", "default"])
def test_response_tier_confirmation_no_retry(monkeypatch, tier, requested_tier):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "service_tier": tier,
                "usage": {"input_tokens": 3, "output_tokens": 1},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "{}"}],
                    }
                ],
            },
        )

    if tier == requested_tier:
        _, meta = call(
            {"model": "gpt-6.1-sol", "service_tier": requested_tier},
            lambda x: x,
            transport=httpx.MockTransport(handler),
        )
        assert meta["returned_service_tier"] == requested_tier
    else:
        with pytest.raises(DiagnosticError) as exc:
            call(
                {"model": "gpt-6.1-sol", "service_tier": requested_tier},
                lambda x: x,
                transport=httpx.MockTransport(handler),
            )
        assert exc.value.diagnostic["code"] == "api_service_tier_mismatch"
        assert exc.value.diagnostic["usage"]["input_tokens"] == 3
    assert len(seen) == 1 and seen[0]["service_tier"] == requested_tier


@pytest.mark.parametrize("requested_tier", ["flex", "default"])
def test_regression_override_and_adapter(tmp_path, requested_tier):
    baseline = source(tmp_path / "baseline", outcome="PASS")
    plan = replay_plan([baseline], repeats=2, model="gpt-6.1-sol", service_tier=requested_tier)
    cfg = CampaignConfig.model_validate(plan["cases"][0]["target_config"])
    argv = command(cfg, tmp_path / "scene.json", tmp_path / "run")
    assert argv[argv.index("--service-tier") + 1] == requested_tier
    assert "--model=gpt-6.1-sol" in argv
    assert plan["max_attempts"] == 2 and plan["afs_requests"] == 0
    assert plan["robot_api_call_upper_bound"] == 2 * cfg.robot.max_calls


class FlexProposer(Proposer):
    def __call__(self, body, **kwargs):
        result = super().__call__(body, **kwargs)
        result["service_tier"] = "flex"
        return result


def test_afs_flex_persisted_and_resume(tmp_path):
    budget = SearchBudget(afs_model="gpt-6.1-sol", afs_service_tier="flex", max_attempts=2)
    proposer = FlexProposer()
    engine, robot, _ = setup(tmp_path, budget=budget, proposer=proposer)
    engine.run(live=True, max_new_attempts=1)
    assert proposer.calls[0]["service_tier"] == "flex"
    assert proposer.calls[0]["model"] == "gpt-6.1-sol"
    assert engine.state["proposals"][0]["returned_service_tier"] == "flex"
    reload(engine, robot, proposer).run(live=True, max_new_attempts=1)


def test_afs_unconfirmed_tier_stops_before_robot(tmp_path):
    budget = SearchBudget(afs_service_tier="flex", max_attempts=2)
    engine, robot, proposer = setup(tmp_path, budget=budget)
    with pytest.raises(ValueError, match="service_tier"):
        engine.run(live=True)
    assert len(proposer.calls) == 1 and not robot.calls
    assert engine.state["proposals"][0]["usage"]["input_tokens"] == 123


def test_saved_flex_response_resumes_without_resend(tmp_path, monkeypatch):
    budget = SearchBudget(afs_model="gpt-6.1-sol", afs_service_tier="flex", max_attempts=2)
    engine, robot, proposer = setup(tmp_path, budget=budget, proposer=FlexProposer())

    def crash(row):
        raise RuntimeError("after saved flex response")

    monkeypatch.setattr(engine, "_finish_proposal", crash)
    with pytest.raises(RuntimeError, match="saved flex"):
        engine.run(live=True)
    assert len(proposer.calls) == 1 and not robot.calls
    resumed = reload(engine, robot, proposer)
    resumed.run(live=True, max_new_attempts=1)
    assert len(proposer.calls) == 1 and len(robot.calls) == 1
