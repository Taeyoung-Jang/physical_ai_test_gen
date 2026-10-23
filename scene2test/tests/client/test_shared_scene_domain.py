"""Frozen common subdomain: CPU fixtures only, no live robot or paid requests."""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from clear_path.contracts import HumanFixture
from clear_path.scene_space import axes_for_schema
from clear_path.search_domain import check_parameters, checked_domain
from failure_client.experiments.paired_discovery import (
    PairedDesign,
    PairedDiscovery,
    checked_manifest,
    paired_plan,
)
from failure_client.methods.behavior_feedback import uniform_scene
from llm_afs.behavior import context_axes, digest

from .test_afs_contrast import fingerprint, source
from .test_independent_discovery import OutcomeRobot
from .test_paired_discovery import Proposer

PROJECT = Path(__file__).resolve().parents[2]


def design_data():
    return json.loads((PROJECT / "config/paired_navigation_domain_luna.json").read_text())


def setup(tmp_path, proposer=None):
    scene = HumanFixture(corridor_width_m=3.6, box_lateral_fraction=1.0)
    controls = [source(tmp_path / f"control{i}", scene=scene) for i in (0, 1)]
    data = design_data()
    data.update(seeds=[101], valid_per_arm=3, attempts_per_arm=4, afs_requests_per_seed=2)
    data["search"].update(valid_rollout_target=3, max_attempts=4, max_afs_requests=2)
    wrapped = paired_plan(
        controls,
        PairedDesign.model_validate(data),
        fingerprint_fn=fingerprint,
    )
    root = PairedDiscovery.create(tmp_path / "new", wrapped, fingerprint_fn=fingerprint)
    proposer = proposer or Proposer()
    robot = OutcomeRobot("PASS")
    return (
        PairedDiscovery(root, runner=robot, proposer=proposer, fingerprint_fn=fingerprint),
        proposer,
        robot,
    )


@pytest.mark.parametrize(
    "problem", ["missing", "unknown", "wide", "nan", "point", "bool", "schema"]
)
def test_domain_requires_exact_finite_physical_subranges(problem):
    domain = design_data()["scene_domain"]
    if problem == "missing":
        del domain["axes"]["floor_friction"]
    elif problem == "unknown":
        domain["axes"]["extra"] = [0, 1]
    elif problem == "wide":
        domain["axes"]["floor_friction"] = [0, 2]
    elif problem == "nan":
        domain["axes"]["floor_friction"] = [float("nan"), 1]
    elif problem == "point":
        domain["axes"]["floor_friction"] = [0.8, 0.8]
    elif problem == "bool":
        domain["axes"]["floor_friction"] = [False, 1]
    else:
        domain["schema_version"] = "unknown"
    with pytest.raises(ValueError):
        checked_domain(domain)
    with pytest.raises(ValueError):
        PairedDesign.model_validate({**design_data(), "scene_domain": domain})


def test_legacy_sampling_and_context_unchanged_bounded_samples_exact():
    schema = "clear-path-human-v5"
    full = axes_for_schema(schema)
    domain = design_data()["scene_domain"]
    ctx = {"allowed_axes": full}
    assert context_axes(ctx) == full
    altered = copy.deepcopy(ctx)
    altered["allowed_axes"]["floor_friction"] = [0.5, 1.1]
    with pytest.raises(ValueError, match="modified"):
        context_axes(altered)
    active = checked_domain(domain)
    assert context_axes({"allowed_axes": active, "scene_domain": domain}) == active
    for i in range(100):
        values = uniform_scene(101, "test", i, schema=schema, domain=domain)
        assert values == uniform_scene(101, "test", i, schema=schema, domain=domain)
        check_parameters(values, domain)
        assert set(values) == set(full)
    values["floor_friction"] = 0.3  # physically valid, outside the frozen subdomain
    with pytest.raises(ValueError, match="outside frozen"):
        check_parameters(values, domain)


def test_both_arms_bootstrap_proposals_and_reports_use_same_domain(tmp_path):
    e, p, r = setup(tmp_path)
    s = e.run(live=True, max_new_attempts=8, max_new_afs_requests=2)
    assert s["status"] == "COMPLETE" and len(r.calls) == 6 and len(p.calls) == 1
    domain = e.design.scene_domain
    for params in r.calls:
        check_parameters(params, domain)
    assert r.calls[0] == r.calls[1] and r.calls[2] == r.calls[3]
    ctx = p.calls[0]
    assert ctx["scene_domain"] == domain
    assert context_axes(ctx) == checked_domain(domain)
    assert all(not a.plan["history"] for a in e.arms())
    for row in e.random_schedule():
        check_parameters(row["parameters"], domain)
    assert s["domain_id"] == e.manifest["domain_id"]
    assert s["domain_geometry_audit"]["rejected_or_resampled"] == 0
    report = e.report()
    saved = json.loads((report.parent / "summary.json").read_text())
    assert saved["scene_domain"] == domain
    assert s["statistical_superiority_established"] is False
    assert not s["fixed_budget_observation_available"]  # mock remains mock


class OutsideProposer(Proposer):
    def __call__(self, body, **kwargs):
        result = super().__call__(body, **kwargs)
        node = result["output"][0]["content"][0]
        proposal = json.loads(node["text"])
        assert proposal["spaces"][0]["axis"] == "floor_friction"
        proposal["spaces"][0]["value"] = 0.3
        node["text"] = json.dumps(proposal)
        return result


def test_outside_proposal_saved_rejected_without_robot_or_clipping(tmp_path):
    e, p, r = setup(tmp_path, OutsideProposer())
    e.run(live=True, max_new_attempts=4, max_new_afs_requests=1)
    assert len(r.calls) == 4
    e.run(live=True, max_new_attempts=1, max_new_afs_requests=1)
    assert len(r.calls) == 4 and len(p.calls) == 1
    arm = e.arm(101, "afs")
    row = arm.state["proposals"][0]
    assert row["rejection"]["robot_launched"] is False
    assert row["rejection"]["endpoints"][0]["reason"] == "numeric_out_of_bounds"
    assert arm.state["selected"] is None
    raw = json.loads((arm.root / "proposals/proposal_00000/response.json").read_text())
    assert json.loads(raw["output"][0]["content"][0]["text"])["spaces"][0]["value"] == 0.3


@pytest.mark.parametrize("method", ["afs", "random"])
def test_final_dispatch_guard_applies_to_both_methods(tmp_path, monkeypatch, method):
    e, p, r = setup(tmp_path)
    arm = e.arm(101, method)
    params = uniform_scene(101, "guard", schema=arm.cfg.scene_schema, domain=e.design.scene_domain)
    params["floor_friction"] = 0.3
    candidate = {"stage": "cold_start", "axis": None, "parameters": params, "strategy": "fixture"}
    monkeypatch.setattr(arm, "_selection", lambda: (copy.deepcopy(candidate), None))
    with pytest.raises(ValueError, match="outside frozen"):
        arm.run(live=True, max_new_attempts=1)
    assert not r.calls and not arm.state["attempts"]


@pytest.mark.parametrize("field", ["domain_axes", "domain_id", "scene_domain"])
def test_rehashed_manifest_domain_conflicts_refused(tmp_path, field):
    e, _, _ = setup(tmp_path)
    w = copy.deepcopy(e.wrapped)
    if field == "domain_id":
        w["manifest"][field] = "wrong"
    elif field == "domain_axes":
        w["manifest"][field]["floor_friction"] = [0.05, 1.5]
    else:
        w["manifest"][field]["axes"]["floor_friction"] = [0.05, 1.5]
    w["sha256"] = digest(w["manifest"])
    with pytest.raises(ValueError, match="shared scene domain"):
        checked_manifest(w)


def test_bounded_saved_proposal_resume_collects_without_resend(tmp_path):
    e, p, r = setup(tmp_path)
    e.run(live=True, max_new_attempts=4)

    def interrupt(event):
        if event["event"] == "proposal_response_collected":
            raise KeyboardInterrupt("saved bounded response")

    e.on_event = interrupt
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(p.calls) == 1 and len(r.calls) == 4
    e.on_event = None
    e.run(live=True, max_new_attempts=8)
    assert len(p.calls) == 1 and len(r.calls) == 4
    e.run(live=True, max_new_attempts=8)
    assert len(p.calls) == 1 and len(r.calls) == 6
    for params in r.calls:
        check_parameters(params, e.design.scene_domain)


def test_script_dry_run_and_invalid_arguments_never_invoke_uv(tmp_path):
    script = PROJECT / "tools/run_navigation_comparison.sh"
    before = set(tmp_path.iterdir())
    for args, expected in [
        ([], 0),
        (["--dry-run"], 0),
        (["--bad"], 2),
        (["--live", "--continue-after-exclusion"], 2),
    ]:
        result = subprocess.run(
            ["bash", str(script), *args], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert result.returncode == expected
        if expected == 0:
            assert "480" in result.stdout and "--max-new-attempts 48" in result.stdout
    assert set(tmp_path.iterdir()) == before
