"""18-axis AFS synthetic wiring; no real robot/API outcome evidence."""

import copy
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest

from clear_path.contracts import GoalRegionFixture
from clear_path.fixture import box_start, identity, world_xml
from clear_path.scene_space import axes_for_schema
from failure_client.archive.regression_cases import _scene_parameters, build_failure_memory
from failure_client.experiments.afs_contrast import contrast_plan, validate_plan
from failure_client.experiments.research_protocol import CampaignConfig
from failure_client.methods.behavior_feedback import (
    boundary_candidate,
    choose_probe,
    feedback_context,
    proposal_request,
    uniform_scene,
)
from llm_afs import behavior as b
from robot_vlm.navigation_completion import completion_contract

from .test_behavior_memory import _rebind
from .test_corridor_campaign import archive
from .test_discovery_measures import json_write, load
from .test_research_campaign import FakeProposer, reload, setup

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = "clear-path-goal-region-v4"


def config():
    return CampaignConfig.model_validate_json(
        (PROJECT / "config/behavior_afs_goal_region_luna.json").read_text()
    )


class GoalRobot:
    def __init__(self):
        self.calls = []

    def __call__(self, cfg, directory, params):
        self.calls.append((directory.name, copy.deepcopy(params)))
        # Deliberately synthetic oracle, not evidence about G1/box physics.
        root = archive(
            directory / "rollout",
            scene=cfg.scene(params),
            outcome="PASS" if params["box_lateral_fraction"] > 0.5 else "FAIL",
        )
        p = json.loads((root / "protocol.json").read_text())
        p.update(
            model=cfg.robot.model,
            http_read_timeout_s=cfg.robot.response_timeout,
            navigation_completion=completion_contract(cfg.robot.navigation_completion),
        )
        json_write(root / "protocol.json", p)
        decisions = [json.loads(s) for s in (root / "decisions.jsonl").read_text().splitlines()]
        for row in decisions:
            if "provider" in row:
                row["provider"]["request_id"] = "synthetic-" + directory.name
        (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in decisions))
        _rebind(root)
        return {"returncode": 0, "wall_s": 0.25, "interrupted": None}


class GoalProposer(FakeProposer):
    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        node = response["output"][0]["content"][0]
        proposal = json.loads(node["text"])
        proposal["spaces"][0].update(axis="box_goal_x_m", low=6.8, high=7.5)
        jsonschema.validate(proposal, body["text"]["format"]["schema"])
        node["text"] = json.dumps(proposal)
        return response


def test_domain_uniform_sampling_and_prospective_budget():
    c = config()
    assert len(c.design()["axes"]) == 18
    assert c.robot.navigation_completion == "goal_dwell_v1"
    assert c.robot.model == c.afs_model == "gpt-6-luna"
    assert c.design()["robot_api_call_upper_bound"] == 120
    assert c.design()["afs_request_upper_bound"] == 2
    assert (
        c.design()["domain_id"]
        != CampaignConfig(scene_schema="clear-path-obstacles-v3").design()["domain_id"]
    )
    for seed in range(20):
        p = uniform_scene(seed, "goal", schema=SCHEMA)
        assert p == uniform_scene(seed, "goal", schema=SCHEMA)
        assert set(p) == set(axes_for_schema(SCHEMA))
        assert c.scene(p).schema_version == SCHEMA


def test_full_cycle_resume_equal_random_and_no_hidden_budget_growth(tmp_path):
    direct, robot_a, proposer_a = setup(
        tmp_path / "direct", config=config(), robot=GoalRobot(), proposer=GoalProposer()
    )
    resumed, robot_b, proposer_b = setup(
        tmp_path / "resume", config=config(), robot=GoalRobot(), proposer=GoalProposer()
    )
    assert direct.run()["status"] == "COMPLETE"
    resumed.run(max_new_attempts=5)
    resumed = reload(resumed, robot_b, proposer_b)
    assert resumed.run()["status"] == "COMPLETE"
    assert robot_a.calls == robot_b.calls and len(robot_a.calls) == 12
    assert len(proposer_a.calls) == len(proposer_b.calls) == 2
    assert [a["valid"] for a in direct.summary()["arms"]] == [6, 6]
    afs = [a for a in direct.state["attempts"] if a["method"] == "afs"]
    random = [a for a in direct.state["attempts"] if a["method"] == "random"]
    for i in range(2):
        assert afs[i]["candidate"]["parameters"] == random[i]["candidate"]["parameters"]
    assert afs[4]["candidate"]["strategy"] == "independent_exploration"
    assert afs[5]["candidate"]["strategy"] == "control_repeat"
    for body in proposer_a.calls:
        enum = body["text"]["format"]["schema"]["$defs"]["Space"]["properties"]["axis"]["enum"]
        assert set(enum) == set(axes_for_schema(SCHEMA))
        assert "max_output_tokens" not in body
    assert direct.report(with_memory=True).is_file()


def test_llm_can_propose_easing_coverage_without_selecting_robot_action(tmp_path):
    root = archive(tmp_path / "covered", scene=GoalRegionFixture(), outcome="FAIL")
    memory = build_failure_memory([load(root)])
    ctx = feedback_context(memory, history_limit=8, remaining=4, scene_schema=SCHEMA)
    assert ctx["scene_graph"]["meta"]["initial_goal_relation"]["relation"] == "FULLY_COVERED"
    raw = {
        "context_sha256": b.digest(ctx),
        "spaces": [
            {
                "mode": "success_probe",
                "axis": "box_lateral_fraction",
                "low": 0.5,
                "high": 1.0,
                "evidence_refs": ["case_memory"],
                "hypothesis": "reduce initial coverage",
                "alternative": "navigation may still fail",
                "falsification": "observe goal result",
            }
        ],
    }
    body = proposal_request(ctx, "gpt-6-luna")
    jsonschema.validate(raw, body["text"]["format"]["schema"])
    candidate = choose_probe(raw, ctx, memory)
    assert candidate["parameters"]["box_lateral_fraction"] == 1.0
    assert candidate["strategy"] == "success_probe"
    assert candidate["boundary_confirmed"] is False
    assert {
        k
        for k in candidate["parameters"]
        if candidate["parameters"][k] != ctx["latest"]["parameters"][k]
    } == {"box_lateral_fraction"}
    assert "box_goal_x_m" in body["instructions"]
    with pytest.raises(ValueError):
        feedback_context(
            memory, history_limit=8, remaining=4, scene_schema="clear-path-obstacles-v3"
        )


def test_box_x_brackets_contrasts_and_reject_tampered_scene(tmp_path):
    low = archive(tmp_path / "low", scene=GoalRegionFixture(box_goal_x_m=6.8), outcome="PASS")
    high = archive(tmp_path / "high", scene=GoalRegionFixture(box_goal_x_m=7.5), outcome="FAIL")
    memory = build_failure_memory([load(low), load(high)])
    assert len(memory["brackets"]) == 1
    assert memory["brackets"][0]["axis"] == "box_goal_x_m"
    assert boundary_candidate(memory)["parameters"]["box_goal_x_m"] == pytest.approx(7.15)
    plan = contrast_plan([low], axis="box_goal_x_m", values=[7.0, 7.5])
    validate_plan(plan)
    assert len(plan["cases"]) == plan["max_attempts"] == 3
    tree = ET.parse(high / "scene.xml")
    tree.getroot().find("worldbody/body[@name='clear_box']").set("pos", "4 0 .35")
    tree.write(high / "scene.xml", encoding="unicode")
    _rebind(high)
    assert _scene_parameters(high, json.loads((high / "protocol.json").read_text()))[0] is None
    assert not build_failure_memory([load(low), load(high)])["brackets"]


def test_plan_only_cli_needs_no_key_and_does_not_launch(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "tools/run_afs_pilot.py"),
            "--config",
            str(PROJECT / "config/behavior_afs_goal_region_luna.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert '"scene_schema": "clear-path-goal-region-v4"' in r.stdout
    assert "AFS_CAMPAIGN=" not in r.stdout and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "outcome,offset,family",
    [
        ("FAIL", 0.0, "goal_occupied"),
        ("FAIL", 0.5, None),
        ("PASS", 1.0, None),
    ],
)
def test_existing_taxonomy_reads_v4_geometry_without_new_goal_rules(
    tmp_path, outcome, offset, family
):
    from failure_client.evaluation.failure_taxonomy import classify_record

    from .test_usage_taxonomy import dense_archive, lines

    root = dense_archive(tmp_path / "trace", outcome=outcome, occupied=True)
    scene = GoalRegionFixture(box_lateral_fraction=offset)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol.update(scene_config=scene.model_dump(), scene_revision=identity(scene))
    json_write(root / "protocol.json", protocol)
    (root / "scene.xml").write_text(world_xml(scene))
    states = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
    for row in states:
        row["qpos"][7:9] = list(box_start(scene))
    lines(root / "states.jsonl", states)
    _rebind(root)
    result = classify_record(load(root))
    assert result.status == "VALID" and result.task_outcome == outcome
    assert result.taxonomy["primary_family"] == family, result.taxonomy
    assert result.taxonomy["families"]["human_safety_risk"]["status"] == "UNSUPPORTED"
