"""Luna opt-in wiring and bounded synthetic campaign, not live model evidence."""

import json
import os
import subprocess
import sys
from pathlib import Path

from failure_client.experiments.local_goal_adapter import command
from failure_client.experiments.research_protocol import CampaignConfig
from robot_vlm.policy import Observation
from robot_vlm.push_policy import PushPolicy

from .test_research_campaign import setup

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT / "config/behavior_afs_luna_smoke.json"


def luna_config():
    return CampaignConfig.model_validate_json(CONFIG.read_text())


def test_luna_changes_models_and_campaign_budget_not_episode_contract():
    luna = luna_config()
    astra = CampaignConfig.model_validate_json(
        (PROJECT / "config/behavior_afs_benchmark.json").read_text()
    )
    assert luna.afs_model == luna.robot.model == "gpt-6-luna"
    assert astra.afs_model == astra.robot.model == "gpt-6-astra"
    assert luna.robot.model_dump(exclude={"model"}) == astra.robot.model_dump(exclude={"model"})
    changed = {
        "afs_model",
        "robot",
        "valid_budget_per_seed",
        "max_attempts_per_arm",
        "max_proposals_per_seed",
    }
    assert luna.model_dump(exclude=changed) == astra.model_dump(exclude=changed)
    assert (luna.valid_budget_per_seed, luna.max_attempts_per_arm, luna.cold_start) == (3, 3, 2)
    assert luna.max_proposals_per_seed == 1


def test_luna_plan_is_cost_bounded_and_has_no_side_effects(tmp_path):
    output = tmp_path / "not-created"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "tools/run_afs_pilot.py"),
            "--config",
            str(CONFIG),
            "--output-dir",
            str(output),
        ],
        cwd=tmp_path,
        env={**os.environ, "OPENAI_API_KEY": "", "PYTHONPATH": str(PROJECT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout.splitlines()[0].removeprefix("PILOT_PLAN="))
    assert plan["robot_model"] == plan["afs_model"] == "gpt-6-luna"
    assert plan["valid_rollouts_total"] == plan["max_attempts_total"] == 6
    assert plan["robot_api_call_upper_bound"] == 60
    assert plan["afs_request_upper_bound"] == 1
    assert plan["max_simulation_s"] is None
    assert "PLAN_ONLY" in result.stdout
    assert not output.exists()


def test_luna_synthetic_campaign_exercises_proposal_and_random(tmp_path):
    engine, robot, proposer = setup(tmp_path, config=luna_config())
    summary = engine.run()
    assert summary["status"] == "COMPLETE"
    assert [arm["valid"] for arm in summary["arms"]] == [3, 3]
    assert len(robot.calls) == 6
    assert len(proposer.calls) == 1
    assert proposer.calls[0]["model"] == "gpt-6-luna"
    attempts = engine.state["attempts"]
    afs = [a for a in attempts if a["method"] == "afs"]
    random = [a for a in attempts if a["method"] == "random"]
    for index in range(2):
        assert afs[index]["candidate"]["parameters"] == random[index]["candidate"]["parameters"]
        assert afs[index]["candidate"]["strategy"] == "paired_uniform_cold_start"
    assert afs[2]["candidate"]["strategy"] == "success_probe"
    assert random[2]["candidate"]["strategy"] == "full_domain_uniform"
    assert summary["excluded"] == 0


def test_luna_robot_command_preserves_goal_profile_and_unlimited_simulation(tmp_path):
    argv = command(luna_config(), tmp_path / "scene.json", tmp_path / "rollout")
    assert "--model=gpt-6-luna" in argv
    assert argv[argv.index("--max-calls") + 1] == "10"
    assert argv[argv.index("--evaluation-profile") + 1] == "goal_outcome_v1"
    assert "--max-seconds" not in argv
    assert "--enable-push" in argv


def test_luna_multimodal_request_changes_only_model():
    observation = Observation(
        state_version=1,
        simulation_time_s=2.0,
        goal_xy_m=[7.0, 0.0],
        base_xyz_m=[1.0, 0.0, 0.74],
        yaw_rad=0.0,
        geometry=[],
        previous_execution="none",
        camera_name="robot",
        camera_fovy_deg=65.0,
        camera_xyz_m=[1.1, 0.0, 1.0],
        camera_rotation_matrix=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    )
    png = b"\x89PNG\r\n\x1a\nsynthetic-contract-test"
    body = PushPolicy(model="gpt-6-luna").body(observation, png)
    astra = PushPolicy(model="gpt-6-astra").body(observation, png)
    assert body == astra | {"model": "gpt-6-luna"}
    assert body["input"][0]["content"][1]["type"] == "input_image"
    assert body["text"]["format"]["strict"] is True
    assert body["reasoning"] == {"effort": "high"}
