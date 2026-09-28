"""Synthetic five-axis closed loop; outcomes are test inputs, not robot capability."""

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest

from clear_path.contracts import CorridorFixture
from clear_path.fixture import identity, world_xml
from clear_path.scene_space import axes_for_schema
from failure_client.archive.regression_cases import _scene_parameters, build_failure_memory
from failure_client.experiments.research_protocol import CampaignConfig
from failure_client.methods.behavior_feedback import (
    boundary_candidate,
    choose_probe,
    feedback_context,
    proposal_request,
    uniform_scene,
)
from llm_afs import behavior as b

from .test_behavior_memory import _rebind, fixture
from .test_discovery_measures import json_write, load
from .test_research_campaign import FakeProposer, reload, setup

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = "clear-path-corridor-v2"


def config():
    return CampaignConfig.model_validate_json(
        (PROJECT / "config/behavior_afs_corridor_luna.json").read_text()
    )


def archive(root, *, width=4.0, offset=0.0, outcome="PASS", mass=2.0):
    root = fixture(root, outcome=outcome)
    scene = CorridorFixture(corridor_width_m=width, box_lateral_fraction=offset, box_mass_kg=mass)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol.update(scene_config=scene.model_dump(), scene_revision=identity(scene))
    json_write(root / "protocol.json", protocol)
    (root / "scene.xml").write_text(world_xml(scene))
    _rebind(root)
    return root


class CorridorRobot:
    def __init__(self):
        self.calls = []

    def __call__(self, cfg, directory, params):
        self.calls.append((directory.name, copy.deepcopy(params)))
        scene = cfg.scene(params)
        root = archive(
            directory / "rollout",
            width=scene.corridor_width_m,
            outcome="PASS" if scene.corridor_width_m >= 3 else "FAIL",
        )
        protocol = json.loads((root / "protocol.json").read_text())
        protocol.update(
            scene_config=scene.model_dump(),
            scene_revision=identity(scene),
            model=cfg.robot.model,
            http_read_timeout_s=cfg.robot.response_timeout,
        )
        json_write(root / "protocol.json", protocol)
        (root / "scene.xml").write_text(world_xml(scene))
        decisions = [
            json.loads(line) for line in (root / "decisions.jsonl").read_text().splitlines()
        ]
        for row in decisions:
            if "provider" in row:
                row["provider"]["request_id"] = "synthetic-" + directory.name
        (root / "decisions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in decisions))
        _rebind(root)
        return {"returncode": 0, "wall_s": 0.25, "interrupted": None}


class CorridorProposer(FakeProposer):
    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        node = response["output"][0]["content"][0]
        proposal = json.loads(node["text"])
        proposal["spaces"][0].update(axis="corridor_width_m", low=1.6, high=4.0)
        node["text"] = json.dumps(proposal)
        return response


def test_domain_and_budget_do_not_relabel_legacy_space():
    cfg = config()
    design = cfg.design()
    assert len(design["axes"]) == 5
    assert design["domain_id"] != CampaignConfig().design()["domain_id"]
    assert design["robot_api_call_upper_bound"] == 120
    assert design["afs_request_upper_bound"] == 2
    assert cfg.robot.model == cfg.afs_model == "gpt-6-luna"
    for seed in range(10):
        a = uniform_scene(seed, "draw", schema=SCHEMA)
        assert a == uniform_scene(seed, "draw", schema=SCHEMA)
        assert cfg.scene(a).schema_version == SCHEMA
        assert set(a) == set(design["axes"])


def test_full_cycle_resume_model_forwarding_and_budget(tmp_path):
    direct, robot_a, proposer_a = setup(
        tmp_path / "direct", config=config(), robot=CorridorRobot(), proposer=CorridorProposer()
    )
    resumed, robot_b, proposer_b = setup(
        tmp_path / "resumed", config=config(), robot=CorridorRobot(), proposer=CorridorProposer()
    )
    assert direct.run()["status"] == "COMPLETE"
    resumed.run(max_new_attempts=5)
    resumed = reload(resumed, robot_b, proposer_b)
    assert resumed.run()["status"] == "COMPLETE"
    assert robot_a.calls == robot_b.calls
    assert len(robot_a.calls) == 12
    assert [a["valid"] for a in direct.summary()["arms"]] == [6, 6]
    assert 1 <= len(proposer_a.calls) <= 2
    assert len(proposer_a.calls) == len(proposer_b.calls)
    for request in proposer_a.calls:
        assert request["model"] == "gpt-6-luna"
        assert set(
            request["text"]["format"]["schema"]["$defs"]["Space"]["properties"]["axis"]["enum"]
        ) == set(axes_for_schema(SCHEMA))
    attempts = direct.state["attempts"]
    afs = [a for a in attempts if a["method"] == "afs"]
    random = [a for a in attempts if a["method"] == "random"]
    assert afs[4]["candidate"]["strategy"] == "independent_exploration"
    assert afs[5]["candidate"]["strategy"] == "control_repeat"
    for i in range(2):
        assert afs[i]["candidate"]["parameters"] == random[i]["candidate"]["parameters"]
    report = direct.report(with_memory=True)
    assert report.is_file()
    assert not list(report.parent.rglob("*.gif"))


def test_geometry_axis_feedback_and_schema_reject_unadvertised_axes(tmp_path):
    memory = build_failure_memory([load(archive(tmp_path / "a", width=1.6, outcome="FAIL"))])
    ctx = feedback_context(memory, history_limit=8, remaining=4, scene_schema=SCHEMA)
    body = proposal_request(ctx, "gpt-6-luna")
    raw = {
        "context_sha256": b.digest(ctx),
        "spaces": [
            {
                "mode": "success_probe",
                "axis": "corridor_width_m",
                "low": 3.0,
                "high": 4.0,
                "evidence_refs": ["case_memory"],
                "hypothesis": "test",
                "alternative": "test",
                "falsification": "test",
            }
        ],
    }
    jsonschema.validate(raw, body["text"]["format"]["schema"])
    candidate = choose_probe(raw, ctx, memory)
    assert candidate["parameters"]["corridor_width_m"] == 4.0
    assert all(
        candidate["parameters"][k] == ctx["latest"]["parameters"][k]
        for k in axes_for_schema(SCHEMA)
        if k != "corridor_width_m"
    )
    bad = copy.deepcopy(raw)
    bad["spaces"][0]["axis"] = "robot_speed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, body["text"]["format"]["schema"])
    with pytest.raises(ValueError):
        feedback_context(memory, history_limit=8, remaining=4)  # wrong frozen schema
    legacy = build_failure_memory([load(fixture(tmp_path / "legacy"))])
    legacy_ctx = feedback_context(legacy, history_limit=8, remaining=4)
    raw["context_sha256"] = b.digest(legacy_ctx)
    with pytest.raises(ValueError, match="not enabled"):
        b.validate(b.Proposal.model_validate(raw), legacy_ctx)


def test_geometry_bracket_requires_single_axis_and_same_residual_xml(tmp_path):
    low = archive(tmp_path / "low", width=1.6, outcome="FAIL")
    high = archive(tmp_path / "high", width=4.0)
    memory = build_failure_memory([load(low), load(high)])
    assert len(memory["brackets"]) == 1
    bracket = memory["brackets"][0]
    assert bracket["axis"] == "corridor_width_m"
    assert bracket["normalized_width"] == pytest.approx(1.0)
    assert boundary_candidate(memory)["parameters"]["corridor_width_m"] == pytest.approx(2.8)
    mixed = archive(tmp_path / "mixed", width=1.6, outcome="PASS")
    assert not build_failure_memory([load(low), load(high), load(mixed)])["brackets"]
    two_axes = archive(tmp_path / "two", width=4.0, mass=1.0)
    assert not build_failure_memory([load(low), load(two_axes)])["brackets"]
    tree = ET.parse(high / "scene.xml")
    tree.getroot().find("option").set("gravity", "0 0 -8")
    tree.write(high / "scene.xml", encoding="unicode")
    _rebind(high)
    assert not build_failure_memory([load(low), load(high)])["brackets"]


@pytest.mark.parametrize("change", ["wall", "box_position", "box_size", "floor"])
def test_scene_audit_rejects_xml_config_disagreement(tmp_path, change):
    root = archive(tmp_path / "run")
    tree = ET.parse(root / "scene.xml")
    tag, name, attribute, value = {
        "wall": ("geom", "wall_north", "pos", "4 1.9 .6"),
        "box_position": ("body", "clear_box", "pos", "4 1 .35"),
        "box_size": ("geom", "clear_box_geom", "size", ".1 .1 .1"),
        "floor": ("geom", "clear_floor", "friction", ".1 .005 .0001"),
    }[change]
    tree.getroot().find(f".//{tag}[@name='{name}']").set(attribute, value)
    tree.write(root / "scene.xml", encoding="unicode")
    _rebind(root)
    params, geometry, warning = _scene_parameters(
        root, json.loads((root / "protocol.json").read_text())
    )
    assert params is geometry is None and warning


def test_campaign_excludes_wrong_geometry_before_goal_failure_count(tmp_path):
    robot = CorridorRobot()

    def corrupted(cfg, directory, params):
        receipt = robot(cfg, directory, params)
        root = directory / "rollout"
        tree = ET.parse(root / "scene.xml")
        tree.getroot().find(".//body[@name='clear_box']").set("pos", "4 2 .35")
        tree.write(root / "scene.xml", encoding="unicode")
        _rebind(root)
        return receipt

    engine, _, _ = setup(tmp_path, config=config(), robot=corrupted, proposer=CorridorProposer())
    summary = engine.run()
    assert summary["status"] == "INCOMPLETE"
    assert summary["reason"] == "scene_geometry_mismatch"
    assert all(a["valid"] == 0 for a in summary["arms"])
    assert len(robot.calls) == 1
