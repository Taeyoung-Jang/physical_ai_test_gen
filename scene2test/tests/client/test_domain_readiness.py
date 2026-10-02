"""Offline capabilities, not simulated outcomes or a live coverage claim."""

import hashlib
import json
import math
import random
import subprocess
import sys
from pathlib import Path

import pytest

from clear_path import fixture
from clear_path.contracts import parse_fixture
from clear_path.obstacles import static_obstacles
from clear_path.scene_space import axes_for_schema
from failure_client.evaluation import domain_readiness as domain
from failure_client.evaluation.research_records import FAMILIES
from failure_client.reporting.domain_readiness_report import write_domain_audit
from robot_vlm.task_outcome import digest, task_contract

PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("schema,count", list(zip(domain.SCHEMAS, (3, 5, 17, 18))))
def test_inventory_never_claims_observed_coverage(schema, count):
    report = domain.audit_domain(schema)
    assert report["axis_count"] == count
    assert report["axes"] == axes_for_schema(schema)
    assert [f["family"] for f in report["families"]] == list(FAMILIES)
    rules = {
        f["family"] for f in report["families"] if f["rule_status"] == "IMPLEMENTED_OPERATIONAL"
    }
    assert rules == {"collision", "obstacle_interference", "goal_occupied"}
    assert all(f["observed_failure_count"] is None for f in report["families"])
    assert all(f["observed_status"] == "NOT_MEASURED" for f in report["families"])
    assert report["execution"] == {"robot_rollouts": 0, "api_calls": 0, "goal_labels_assigned": 0}
    r = report["target_readiness"]
    assert r["status"] == "INSUFFICIENT_RULE_SUPPORT"
    assert r["implemented_rule_count"] == 3 and r["minimum_additional_rules_needed"] == 1
    assert r["observed_failure_diversity_coverage"] is None


@pytest.mark.parametrize("schema", domain.SCHEMAS[:3])
def test_initial_goal_separation_is_not_post_action_impossibility(schema):
    r = domain.audit_domain(schema)
    g = r["initial_goal_occupancy"]
    assert g["status"] == "PROVEN_DISJOINT_AT_INITIALIZATION"
    assert g["initial_occupancy_possible"] is False
    assert g["post_action_occupancy_possible"] is None
    assert all(row["goal_disk_separation_lower_bound_m"] > 0 for row in g["envelopes"])
    families = {f["family"]: f for f in r["families"]}
    assert families["goal_occupied"]["rule_status"] == "IMPLEMENTED_OPERATIONAL"
    assert families["goal_occupied"]["scene_control_status"] == "NO_INITIAL_OCCUPANCY_IN_DOMAIN"
    assert families["unreachable"]["rule_status"] == "UNSUPPORTED"


@pytest.mark.parametrize("schema", domain.SCHEMAS)
def test_envelopes_contain_actual_geometry_at_extremes_and_seeded_samples(schema):
    envelopes = {r["object_id"]: r["xy_envelope_m"] for r in domain.initial_envelopes(schema)}
    bounds = axes_for_schema(schema)
    rng = random.Random(17)
    samples = [{k: lo for k, (lo, hi) in bounds.items()}, {k: hi for k, (lo, hi) in bounds.items()}]
    samples += [{k: rng.uniform(*v) for k, v in bounds.items()} for _ in range(150)]
    if schema in ("clear-path-obstacles-v3", "clear-path-goal-region-v4"):
        for yaw in (-90.0, -45.0, 0.0, 45.0, 90.0):
            for side in (-1.0, 1.0):
                row = samples[1].copy()
                for i in (1, 2):
                    row[f"obstacle_{i}_yaw_deg"] = yaw
                    row[f"obstacle_{i}_lateral_fraction"] = side
                samples.append(row)
    for params in samples:
        cfg = parse_fixture({"schema_version": schema, **params})
        actual = dict(fixture.walls(cfg))
        x, y = fixture.box_start(cfg)
        sx, sy, _ = fixture.BOX_SIZE
        actual["clear_box"] = (x - sx / 2, x + sx / 2, y - sy / 2, y + sy / 2)
        actual.update({o["id"]: o["aabb_xy_m"] for o in static_obstacles(cfg)})
        assert actual.keys() == envelopes.keys()
        for name, (x0, x1, y0, y1) in actual.items():
            ex0, ex1, ey0, ey1 = envelopes[name]
            assert ex0 - 1e-10 <= x0 <= x1 <= ex1 + 1e-10
            assert ey0 - 1e-10 <= y0 <= y1 <= ey1 + 1e-10


def test_rotated_max_extent_proof_and_no_envelope_overlap_false_positive():
    env = {r["object_id"]: r for r in domain.initial_envelopes(domain.SCHEMAS[2])}
    xmax = env["obstacle_2"]["xy_envelope_m"][1]
    assert xmax == pytest.approx(5.75 + math.hypot(0.8, 0.8) / 2)
    assert xmax < 7.0 - 0.25
    goal = task_contract([4.0, 0.0], 10, None)["goal"]
    check = domain._initial_goal_check(domain.SCHEMAS[2], goal)
    assert check["status"] == "UNKNOWN"
    assert check["initial_occupancy_possible"] is None  # envelope overlap is NOT a witness


def test_map_probe_does_not_become_goal_failure():
    r = domain.audit_domain(domain.SCHEMAS[2])
    assert {p["static_map_reachable"] for p in r["static_map_probes"]} == {False, True}
    assert all(p["goal_outcome"] is None for p in r["static_map_probes"])
    assert r["families"][list(FAMILIES).index("unreachable")]["rule_status"] == "UNSUPPORTED"
    assert r["initial_goal_occupancy"]["initial_occupancy_possible"] is False


def test_v4_constructive_examples_do_not_invent_success_or_fourth_family():
    r = domain.audit_domain("clear-path-goal-region-v4")
    g = r["initial_goal_occupancy"]
    assert g["initial_occupancy_possible"] is True
    assert g["status"] == "CONSTRUCTIVE_INITIAL_OCCUPANCY"
    assert g["post_action_occupancy_possible"] is None
    assert {w["relation"]["relation"] for w in g["constructive_examples"]} == {
        "CLEAR",
        "PARTIAL",
        "FULLY_COVERED",
    }
    assert all(w["relation"]["goal_outcome"] is None for w in g["constructive_examples"])
    assert r["target_readiness"]["implemented_rule_count"] == 3
    human = next(f for f in r["families"] if f["family"] == "human_safety_risk")
    assert human["rule_status"] == "UNSUPPORTED"
    assert human["development_status"] == "EXPERIMENTAL_MEASUREMENT_CONTRACT_ONLY"


def test_rule_count_is_inventory_not_discovery_even_with_four_rules(monkeypatch):
    monkeypatch.setattr(domain, "RULES", {f: "synthetic-test-rule" for f in FAMILIES[:4]})
    r = domain.audit_domain()
    assert r["target_readiness"]["implemented_rule_count"] == 4
    assert r["target_readiness"]["status"] == "REQUIRES_VALIDATED_SCENARIOS_AND_ROLLOUTS"
    assert r["target_readiness"]["observed_failure_diversity_coverage"] is None


def test_unknown_schema_and_source_hash_bound_audit():
    with pytest.raises(ValueError, match="reviewed"):
        domain.audit_domain("terrain-future-v9")
    a = domain.audit_domain()
    assert a == domain.audit_domain()
    payload = {k: v for k, v in a.items() if k != "audit_sha256"}
    assert a["audit_sha256"] == digest(payload)
    src = PROJECT / "src"
    for relative, sha in a["source_hashes"].items():
        assert hashlib.sha256((src / relative).read_bytes()).hexdigest() == sha


def test_report_is_separate_non_overwriting_and_hashed(tmp_path):
    report = domain.audit_domain()
    dest = tmp_path / "report"
    result = write_domain_audit(dest, report)
    assert result == dest / "report.html"
    saved = json.loads((dest / "audit.json").read_text())
    # JSON represents the source's tuple axis bounds as arrays; compare canonically.
    assert saved == json.loads(json.dumps(report))
    assert saved["target_readiness"]["observed_failure_diversity_coverage"] is None
    manifest = json.loads((dest / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == sha
    prior = result.read_bytes()
    with pytest.raises(FileExistsError):
        write_domain_audit(dest, report)
    assert result.read_bytes() == prior
    report["axis_count"] = 99
    with pytest.raises(ValueError, match="digest"):
        write_domain_audit(tmp_path / "bad", report)
    assert not (tmp_path / "bad").exists()


def test_html_escapes_dynamic_strings(tmp_path):
    a = domain.audit_domain()
    a["families"][0]["gap"] = "<script>bad()</script>"
    a["audit_sha256"] = digest({k: v for k, v in a.items() if k != "audit_sha256"})
    report = write_domain_audit(tmp_path / "html", a).read_text()
    assert "<script>bad()" not in report
    assert "&lt;script&gt;bad()" in report


def test_cli_stdout_without_network_gpu_or_mutations(tmp_path):
    # Fail hard if an audit tries to import a simulation/inference backend or connect.
    code = """
import importlib.abc, runpy, socket, sys
class RejectHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mujoco', 'onnxruntime', 'openai', 'torch'}:
            raise AssertionError('forbidden heavy import: ' + fullname)
sys.meta_path.insert(0, RejectHeavy())
def denied(*args, **kwargs):
    raise AssertionError('network must not be used')
socket.socket.connect = denied
sys.argv = ['audit_failure_domain.py', '--stdout-only']
runpy.run_path(AUDIT_SCRIPT, run_name='__main__')
"""
    # Explicit repository path, independent of CWD; the tool must not create output here.
    code = f"AUDIT_SCRIPT = {str(PROJECT / 'tools/audit_failure_domain.py')!r}\n" + code
    before = list(tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["execution"]["api_calls"] == 0
    assert list(tmp_path.iterdir()) == before


def test_cli_refuses_conflicting_options_and_overwrite(tmp_path):
    cli = [sys.executable, str(PROJECT / "tools/audit_failure_domain.py")]
    out = tmp_path / "audit"
    conflict = subprocess.run(
        cli + ["--stdout-only", "--output-dir", str(out)], capture_output=True, text=True
    )
    assert conflict.returncode == 2 and not out.exists()
    first = subprocess.run(cli + ["--output-dir", str(out)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    before = (out / "audit.json").read_bytes()
    second = subprocess.run(cli + ["--output-dir", str(out)], capture_output=True, text=True)
    assert second.returncode == 2 and "FileExistsError" in second.stderr
    assert (out / "audit.json").read_bytes() == before
