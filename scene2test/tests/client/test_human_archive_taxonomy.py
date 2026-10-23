"""Manifest-bound synthetic traces: contracts/metrics, not observed robot failures."""

import json
import runpy
from pathlib import Path

import pytest

from clear_path import fixture
from clear_path.contracts import HumanFixture
from clear_path.humans import human_scene
from failure_client.evaluation.failure_taxonomy import (
    HUMAN_PROFILE,
    RULES,
    classify_record,
    rules_for_profile,
)
from failure_client.evaluation.human_archive import measure_archive_humans
from failure_client.evaluation.research_records import RunInput
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics

from .test_behavior_memory import _rebind
from .test_discovery_measures import json_write, load, rewrite_manifest
from .test_usage_taxonomy import dense_archive, lines


def human_archive(
    root, *, outcome="FAIL", near=True, collision=False, occupied=False, blocked=False
):
    dense_archive(
        root,
        outcome="FAIL" if outcome == "INCONCLUSIVE" else outcome,
        collision=collision,
        occupied=occupied,
        blocked=blocked,
    )
    config = HumanFixture(
        human_lateral_fraction=0.0 if near else 1.0,
        box_lateral_fraction=0.0 if occupied else 1.0,
        obstacle_1_lateral_fraction=0.0 if blocked else 0.7,
    )
    p = json.loads((root / "protocol.json").read_text())
    p.update(scene_config=config.model_dump(), scene_revision=fixture.identity(config))
    json_write(root / "protocol.json", p)
    (root / "scene.xml").write_text(fixture.world_xml(config))
    json_write(root / "scene_graph.json", fixture.graph(config))
    json_write(root / "human_proxies.json", human_scene(config))
    rows = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
    for row in rows:
        xy = [4.0, 0.7] if near else [3.1, 0.0]
        if outcome == "PASS" and row["time_s"] >= 7.0:
            xy = [7.0, 0.0]
        row["qpos"][:2] = xy
        row["qpos"][7:10] = [*fixture.box_start(config), 0.35]
        row["goal_distance_m"] = ((xy[0] - 7) ** 2 + xy[1] ** 2) ** 0.5
    lines(root / "states.jsonl", rows)
    if outcome == "INCONCLUSIVE":
        from robot_vlm.task_outcome import GoalEvaluator

        result = json.loads((root / "result.json").read_text())
        result.update(GoalEvaluator(p["task_contract"]).result("api_timeout", False))
        result["reason"] = "api_timeout"
        json_write(root / "result.json", result)
    _rebind(root)
    return root


def classified(root, **kwargs):
    return classify_record(load(human_archive(root, **kwargs)), profile=HUMAN_PROFILE)


def test_verified_terminal_exposure_is_fourth_operational_rule(tmp_path):
    record = classified(tmp_path / "near")
    assert record.task_outcome == "FAIL"
    assert record.attribution.primary_family == "human_safety_risk"
    assert record.attribution.causal_status == "UNCONFIRMED"
    m = record.taxonomy["measurements"]["human_proximity"]
    assert m["evidence_binding"] == "VERIFIED_ARCHIVE_SCENE_AND_TRACE"
    assert m["zones"][0]["longest_continuous_exposure_s"] == pytest.approx(5.0)
    assert {"human_proxies.json", "scene_graph.json", "states.jsonl"} <= set(
        record.attribution.evidence_refs
    )
    assert "human_safety_risk" not in RULES  # default v1 contract retained
    assert len(rules_for_profile(HUMAN_PROFILE)) == 4


def test_success_retains_risk_diagnostic_without_failure_attribution(tmp_path):
    record = classified(tmp_path / "pass", outcome="PASS")
    assert record.task_outcome == "PASS" and record.attribution is None
    human = record.taxonomy["families"]["human_safety_risk"]
    assert human["status"] == "N/A" and human["diagnostic_status"] == "DETECTED"
    assert (
        record.taxonomy["measurements"]["human_proximity"]["diagnostic_status"]
        == "EXPOSURE_DETECTED"
    )


def test_clear_gap_and_ambiguous_causes_do_not_invent_family(tmp_path):
    clear = classified(tmp_path / "clear", near=False)
    assert clear.attribution is None
    assert clear.taxonomy["families"]["human_safety_risk"]["status"] == "NOT_DETECTED"
    ambiguous = classified(tmp_path / "mixed", collision=True)
    assert ambiguous.attribution is None
    assert "ambiguous_multiple_families" in ambiguous.taxonomy["warnings"]


@pytest.mark.parametrize(
    "kind", ["metadata", "graph", "xml", "unbound", "gap", "audit", "qpos_layout"]
)
def test_missing_or_inconsistent_human_evidence_is_unknown(tmp_path, kind):
    root = human_archive(tmp_path / "run")
    if kind in {"metadata", "graph"}:
        name = "human_proxies.json" if kind == "metadata" else "scene_graph.json"
        obj = json.loads((root / name).read_text())
        if kind == "metadata":
            obj["proxies"][0]["protected_radius_m"] = 2.0
        else:
            next(o for o in obj["objects"] if o["id"] == "human_proxy_1")["role"] = "obstacle"
        json_write(root / name, obj)
    elif kind == "xml":
        (root / "scene.xml").write_text(
            (root / "scene.xml").read_text().replace('pos="4.0 0.0 0.8"', 'pos="4.2 0.0 0.8"')
        )
    elif kind == "gap":
        rows = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
        lines(root / "states.jsonl", [r for r in rows if not 4 < r["time_s"] < 5])
    elif kind == "audit":
        obj = json.loads((root / "robot_audit.json").read_text())
        obj["robot_joint_identity_preserved"] = False
        json_write(root / "robot_audit.json", obj)
    elif kind == "qpos_layout":
        rows = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
        for row in rows:
            row["qpos"].pop()
        lines(root / "states.jsonl", rows)
    rewrite_manifest(root)
    if kind == "unbound":
        m = json.loads((root / "manifest.json").read_text())
        m["artifacts"] = [r for r in m["artifacts"] if r["path"] != "human_proxies.json"]
        json_write(root / "manifest.json", m)
    record = classify_record(load(root), profile=HUMAN_PROFILE)
    assert record.task_outcome == "FAIL" and record.attribution is None
    assert record.taxonomy["families"]["human_safety_risk"]["status"] == "UNKNOWN"


def test_v1_and_excluded_records_never_acquire_human_label(tmp_path):
    root = dense_archive(tmp_path / "old")
    old = classify_record(load(root), profile=HUMAN_PROFILE)
    assert old.taxonomy["families"]["human_safety_risk"]["status"] == "UNSUPPORTED"
    root = human_archive(tmp_path / "interrupted", outcome="INCONCLUSIVE")
    interrupted = classify_record(load(root), profile=HUMAN_PROFILE)
    assert interrupted.attribution is None and interrupted.task_outcome == "INCONCLUSIVE"
    assert measure_archive_humans(interrupted)["measurement_status"] == "UNKNOWN"


def test_four_distinct_synthetic_families_and_fdr_are_required_together(tmp_path):
    records = [
        classified(tmp_path / "collision", near=False, collision=True),
        classified(tmp_path / "blocked", near=False, blocked=True),
        classified(tmp_path / "occupied", near=False, occupied=True),
        classified(tmp_path / "human"),
    ]
    assert len({r.condition_id for r in records}) == 1
    assert {r.attribution.primary_family for r in records} == set(rules_for_profile(HUMAN_PROFILE))
    summary = calculate_discovery_metrics(records, family_rules=rules_for_profile(HUMAN_PROFILE))[
        "groups"
    ][0]
    assert summary["joint_fdr_diversity_target_observed"] is True
    assert summary["failure_discovery_rate"] == 1
    assert summary["discovered_family_count"] == 4
    assert summary["failure_diversity_coverage"] is None
    assert summary["observed_family_coverage_lower_bound"] == pytest.approx(4 / 6)
    passes = [
        records[0].model_copy(
            update={
                "source": RunInput(path=f"/synthetic/pass{i}"),
                "evidence_id": f"pass{i}",
                "scene_id": f"pass{i}",
                "task_outcome": "PASS",
                "attribution": None,
                "taxonomy": {},
            }
        )
        for i in range(10)
    ]
    summary = calculate_discovery_metrics(
        records + passes, family_rules=rules_for_profile(HUMAN_PROFILE)
    )["groups"][0]
    assert summary["discovered_family_count"] == 4
    assert summary["failure_discovery_rate"] < 0.30
    assert summary["joint_fdr_diversity_target_observed"] is False


def test_cli_v2_report_and_memory_include_verified_human_evidence(tmp_path):
    root = human_archive(tmp_path / "run")
    output = tmp_path / "report"
    main = runpy.run_path(str(Path(__file__).parents[2] / "tools/measure_failure_discovery.py"))[
        "main"
    ]
    main(
        [
            "--run",
            str(root),
            "--with-taxonomy",
            "--taxonomy-profile",
            HUMAN_PROFILE,
            "--with-memory",
            "--output-dir",
            str(output),
        ]
    )
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["groups"][0]["discovered_families"] == ["human_safety_risk"]
    assert metrics["groups"][0]["joint_fdr_diversity_target_observed"] is None
    assert "joint_fdr_diversity_target_observed" in (output / "report.html").read_text()
    assert list((output / "memory").rglob("human_proxies.json"))


def test_human_observations_and_axes_reach_actual_afs_request(tmp_path):
    from failure_client.archive.regression_cases import build_failure_memory
    from failure_client.experiments.research_protocol import CampaignConfig
    from failure_client.methods.behavior_feedback import (
        choose_probe,
        feedback_context,
        proposal_request,
    )
    from llm_afs import behavior, provider

    from .test_research_campaign import FakeProposer

    record = classified(tmp_path / "run")
    memory = build_failure_memory([record])
    config = CampaignConfig(scene_schema="clear-path-human-v5", taxonomy_profile=HUMAN_PROFILE)
    ctx = feedback_context(memory, history_limit=4, remaining=6, scene_schema=config.scene_schema)
    body = proposal_request(ctx, "synthetic-mock")
    assert (
        len(body["text"]["format"]["schema"]["$defs"]["Space"]["properties"]["axis"]["enum"]) == 20
    )
    evidence = next(e for e in ctx["latest"]["evidence"] if e["id"] == record.evidence_id)
    human = evidence["operational_taxonomy"]["human_proximity"]
    assert human["evidence_binding"] == "VERIFIED_ARCHIVE_SCENE_AND_TRACE"
    assert human["zones"][0]["longest_continuous_exposure_s"] == pytest.approx(5.0)
    raw = provider.extract_proposal(FakeProposer()(body))
    raw["spaces"][0].update(axis="human_x_m", low=3.65, high=4.35)
    behavior.validate(behavior.Proposal.model_validate(raw), ctx)
    candidate = choose_probe(raw, ctx, memory)
    assert config.scene(candidate["parameters"]).human_x_m in (3.65, 4.35)
