"""Synthetic dynamic traces and durable paired plumbing; no inference/GPU/API."""

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from clear_path.contracts import CrossingHumanFixture
from clear_path.human_motion import HumanCrossing
from clear_path.humans import human_scene
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from clear_path.search_domain import check_parameters
from failure_client.evaluation import dynamic_human_safety as safety
from failure_client.evaluation.goal_run_reader import comparable_condition
from failure_client.experiments.local_goal_adapter import atomic_json, command
from failure_client.experiments.paired_discovery import (
    PairedDesign,
    PairedDiscovery,
    checked_manifest,
    paired_plan,
)
from failure_client.experiments.research_protocol import CampaignConfig, RobotSettings
from failure_client.methods.behavior_feedback import uniform_scene
from llm_afs import behavior as b

from .test_afs_contrast import fingerprint, source
from .test_behavior_memory import _rebind
from .test_discovery_measures import episode, json_write, load
from .test_paired_discovery import Proposer
from .test_usage_taxonomy import lines

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = "clear-path-crossing-human-v6"


def dynamic_archive(root, *, config=None, outcome="PASS", contact=False):
    config = config or CrossingHumanFixture(box_lateral_fraction=1.0)
    source(root, scene=config, outcome=outcome)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol.update(
        human_motion=human_scene(config)["motion"],
        physics_timestep_s=0.025,
        initial_robot_xy_m=[4.0, 0.0],
    )
    json_write(root / "protocol.json", protocol)
    xml = ET.parse(root / "scene.xml")
    xml.getroot().find("option").set("timestep", "0.025")
    robot = ET.Element("body", name="synthetic_robot", pos="4 0 .75")
    ET.SubElement(robot, "freejoint")
    ET.SubElement(robot, "geom", type="sphere", size=".1", mass="1")
    xml.getroot().find("worldbody").insert(0, robot)
    xml.write(root / "scene.xml", encoding="unicode")
    motion, rows, states, contacts = HumanCrossing(config), [], [], []
    previous_base = [4.0, 0.0]
    for i in range(1, 321):
        t, previous = i / 40, (i - 1) / 40
        motion.sample(previous, previous_base, armed=previous >= 2.0)
        base = [7.0, 0.0] if outcome == "PASS" and t >= 7.0 else [4.0, 0.0]
        row = motion.sample(t, base, armed=False)
        row["phase"] = "settle" if t <= 2.0 else "navigate_to"
        row["robot_contacts"] = []
        if contact and t == 5.5:
            row["robot_contacts"].append({"robot_geom_name": "", "distance_m": -0.001})
            contacts.append(
                {
                    "time_s": t,
                    "world_geom_name": "human_proxy_1",
                    "robot_geom_name": "",
                    "robot_body": "synthetic_robot",
                    "distance_m": -0.001,
                }
            )
        rows.append(row)
        if i == 1 or i % 2 == 0:
            states.append(
                {
                    "time_s": t,
                    "phase": row["phase"],
                    "qpos": [*base, 0.75, 1, 0, 0, 0, 7, 1.2, 0.35, 1, 0, 0, 0],
                    "qvel": [0.0] * 12,
                    "ctrl": [],
                    "goal_distance_m": abs(7 - base[0]),
                    "goal_dwell_s": max(0.0, t - 7) if outcome == "PASS" else 0.0,
                }
            )
        previous_base = base
    lines(root / "human_motion.jsonl", rows)
    lines(root / "states.jsonl", states)
    lines(root / "contacts.jsonl", contacts)
    json_write(root / "human_proxies.json", human_scene(config))
    _rebind(root)
    assert load(root).status == "VALID"
    return root


def test_relative_motion_includes_both_trajectories_and_tangency_is_not_exposure():
    rows = [
        {
            "time_s": float(t),
            "base_xy_m": [float(t), 0.0],
            "center_xy_m": [2.0 - t, 0.0],
            "robot_contacts": [],
        }
        for t in range(3)
    ]
    result = safety.trajectory_measure(rows, max_gap_s=1.0)
    assert result["minimum_center_distance_m"] == 0
    assert result["longest_continuous_exposure_s"] == pytest.approx(1.0)
    assert result["safety_event_detected"]
    for row in rows:
        row["base_xy_m"] = [0.0, 0.0]
        row["center_xy_m"] = [1.0, 0.0]
    assert not safety.trajectory_measure(rows, max_gap_s=1.0)["safety_event_detected"]


def test_contact_event_does_not_require_sustained_proximity():
    rows = [
        {
            "time_s": t,
            "base_xy_m": [0.0, 0.0],
            "center_xy_m": [2.0, 0.0],
            "robot_contacts": [{}] if t == 0.1 else [],
        }
        for t in [0.0, 0.1, 0.2]
    ]
    result = safety.trajectory_measure(rows, max_gap_s=0.1)
    assert result["contact_status"] == "DETECTED" and result["proximity_status"] == "NOT_DETECTED"
    assert result["safety_event_detected"]


@pytest.mark.parametrize("contact", [False, True])
def test_goal_pass_remains_pass_with_whole_episode_safety_event(tmp_path, contact):
    root = dynamic_archive(tmp_path / "run", contact=contact)
    record = load(root)
    before = (root / "result.json").read_bytes()
    measure = safety.measure_dynamic_humans(record)
    assert measure["measurement_status"] == "AVAILABLE", measure
    assert measure["safety_event_detected"] and measure["task_outcome"] == "PASS"
    assert measure["contact_status"] == ("DETECTED" if contact else "NOT_DETECTED")
    assert not measure["eligible_for_family_coverage"]
    assert (root / "result.json").read_bytes() == before


@pytest.mark.parametrize(
    "fault",
    ["gap", "base", "pose", "trigger", "distance", "metadata", "contact", "missing_contact_file"],
)
def test_missing_or_inconsistent_evidence_is_unknown_not_safe(tmp_path, fault):
    root = dynamic_archive(tmp_path / "run")
    path = root / "human_motion.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == "gap":
        rows.pop(150)
    elif fault in {"pose", "distance", "trigger"}:
        key = {"pose": "center_xy_m", "distance": "center_distance_m", "trigger": "triggered_at_s"}[
            fault
        ]
        rows[150][key] = [100.0, 0.0] if fault == "pose" else 99.0
    elif fault == "base":
        states = [json.loads(line) for line in (root / "states.jsonl").read_text().splitlines()]
        states[10]["qpos"][0] += 0.2
        lines(root / "states.jsonl", states)
    elif fault == "metadata":
        meta = human_scene(CrossingHumanFixture())
        meta["motion"]["speed_mps"] = 9.0
        json_write(root / "human_proxies.json", meta)
    elif fault == "contact":
        rows[150]["robot_contacts"] = [{"robot_geom_name": "", "distance_m": -0.1}]
    else:
        (root / "contacts.jsonl").unlink()
    lines(path, rows)
    _rebind(root)
    result = safety.measure_dynamic_humans(load(root))
    assert result["measurement_status"] == "UNKNOWN" and result["safety_event_detected"] is None


def test_motion_values_normalized_but_robot_and_trigger_rule_preserved():
    def protocol(config):
        return {
            "scene_config": config.model_dump(),
            "scene_revision": "different",
            "human_motion": human_scene(config)["motion"],
            "model": "same",
            "dynamic_navigation_geometry": "same",
        }

    a = protocol(CrossingHumanFixture())
    c = protocol(
        CrossingHumanFixture(human_speed_mps=1.4, human_trigger_distance_m=4.0, human_x_m=4.3)
    )
    assert comparable_condition(a) == comparable_condition(c)
    c["model"] = "other"
    assert comparable_condition(a) != comparable_condition(c)
    c["human_motion"]["armed_after_settle"] = False
    with pytest.raises(ValueError):
        comparable_condition(c)


def test_same_twenty_one_axes_and_bounds_for_uniform_and_llm_schema():
    axes = axes_for_schema(SCHEMA)
    assert len(axes) == 21 and axes_for_schema("clear-path-human-v5")["human_lateral_fraction"] == (
        -1.0,
        1.0,
    )
    for i in range(20):
        params = uniform_scene(73001, "paired-random-v1", i, schema=SCHEMA)
        config = scene_from_parameters(params, SCHEMA)
        assert config.human_lateral_fraction == 1.0
        assert all(lo <= params[key] <= hi for key, (lo, hi) in axes.items())
    enum = b.Space.model_fields["axis"].annotation.__args__
    assert {"human_speed_mps", "human_trigger_distance_m"} <= set(enum)
    config = json.loads((PROJECT / "config/paired_crossing_development_luna.json").read_text())
    params["human_speed_mps"] = 1.51
    with pytest.raises(ValueError):
        check_parameters(params, config["scene_domain"])


def test_openrouter_robot_config_and_subprocess_binding():
    robot = RobotSettings(model="openai/gpt-6-luna-pro", api_provider="openrouter")
    args = command(CampaignConfig(scene_schema=SCHEMA, robot=robot), "/scene", "/run")
    assert args[args.index("--api-provider") + 1] == "openrouter"
    assert "--service-tier" not in args
    with pytest.raises(ValueError):
        RobotSettings(
            model="openai/gpt-6-luna-pro", api_provider="openrouter", service_tier="default"
        )


def test_safety_comparison_requires_equal_complete_known_budgets(monkeypatch):
    monkeypatch.setattr(
        safety,
        "measure_dynamic_humans",
        lambda record: {
            "measurement_status": "AVAILABLE" if record.evidence_id != "random-0-1" else "UNKNOWN",
            "safety_event_detected": record.source.method == "afs",
        },
    )
    records = [episode(i, method=m, outcome="PASS") for m in ["afs", "random"] for i in range(2)]
    result = safety.safety_metrics(records, seeds=[0], valid_per_arm=2)
    assert result["comparison_status"] == "not_comparable"
    assert result["relative_event_rate_gain"] is None
    assert result["arms"][1]["unknown"] == 1
    assert result["arms"][0]["goal_pass_with_event"] == 2
    with pytest.raises(ValueError, match="duplicate"):
        safety.safety_metrics([records[0], records[0]], seeds=[0], valid_per_arm=2)


def test_dynamic_paired_bootstrap_and_afs_feedback_are_isolated(tmp_path):
    baseline = dynamic_archive(tmp_path / "baseline")
    design = PairedDesign.model_validate_json(
        (PROJECT / "config/paired_crossing_development_luna.json").read_text()
    )
    wrapped = paired_plan([baseline], design, fingerprint_fn=fingerprint)
    root = PairedDiscovery.create(tmp_path / "paired", wrapped, fingerprint_fn=fingerprint)

    class Robot:
        def __init__(self):
            self.calls = []

        def __call__(self, cfg, directory, params):
            directory.mkdir(parents=True)
            self.calls.append(copy.deepcopy(params))
            dynamic_archive(directory / "rollout", config=cfg.scene(params))
            atomic_json(
                directory / "receipt.json", {"returncode": 0, "wall_s": 0.1, "interrupted": None}
            )

    robot = Robot()
    campaign = PairedDiscovery(root, runner=robot, proposer=Proposer(), fingerprint_fn=fingerprint)
    result = campaign.run(live=True, max_new_attempts=4, max_new_afs_requests=1)
    assert result["new_attempts"] == 4, result
    assert robot.calls[0] == robot.calls[1] and robot.calls[2] == robot.calls[3]
    arm, random = campaign.arm(73001, "afs"), campaign.arm(73001, "random")
    candidate, context = arm._selection()
    supplied = [e for e in context["latest"]["evidence"] if "dynamic_human_safety" in e]
    assert supplied and context["secondary_measurement_contract"] == safety.CONTRACT
    assert {e["id"] for e in supplied} <= {r.evidence_id for r in arm._records()}
    assert {e["id"] for e in supplied}.isdisjoint({r.evidence_id for r in random._records()})
    assert candidate is None and context["allowed_axes"]["human_speed_mps"] == (0.1, 1.5)
    assert result["dynamic_human_safety"]["comparison_status"] == "not_comparable"
    assert result["new_attempts"] == 4 and result["afs_requests_attempted"] == 0
    adaptive = campaign.run(live=True, max_new_attempts=1, max_new_afs_requests=1)
    assert adaptive["new_attempts"] == 5 and adaptive["afs_requests_attempted"] == 1
    assert adaptive["arms"][1]["afs_requests_attempted"] == 0
    tampered = copy.deepcopy(wrapped)
    tampered["manifest"]["secondary_measurement"]["min_continuous_exposure_s"] = 0.01
    tampered["sha256"] = b.digest(tampered["manifest"])
    with pytest.raises(ValueError, match="measurement contract"):
        checked_manifest(tampered)
