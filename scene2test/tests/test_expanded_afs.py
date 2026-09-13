"""Offline expanded contracts/geometry tests; fabricated observations are NOT robot evidence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from llm_afs.expanded import (
    Domain,
    ExpandedConfig,
    ExpandedProposal,
    compile_scenes,
    context,
    demo,
    validate_proposal,
)
from simulation_server.worlds import validate_bundle

PROJECT = Path(__file__).parents[1]


@pytest.fixture
def config():
    return ExpandedConfig.model_validate(
        yaml.safe_load((PROJECT / "config/llm_afs_expanded.yaml").read_text())
    )


def test_context_and_closed_schema(config):
    assert len(json.loads(json.dumps(context(config, [])))["layouts"]) == 4
    schema = ExpandedProposal.model_json_schema()
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


@pytest.mark.parametrize(
    "path", ["planning_max_slope_deg", "segments.0.kind", "segments.99.count", "__class__"]
)
def test_reject_unauthorized_fields(config, path):
    raw = config.model_dump()
    raw["layouts"][0]["domains"][0]["path"] = path
    with pytest.raises(ValueError):
        ExpandedConfig.model_validate(raw)


@pytest.mark.parametrize(
    "mutation", ["identity", "bounds", "kind", "choice", "layout", "duplicate"]
)
def test_proposal_rejection(config, mutation):
    raw = demo(config).model_dump()
    space = raw["spaces"][0]
    if mutation == "identity":
        raw["config_sha256"] = "wrong"
    elif mutation == "bounds":
        space["domains"][0]["high"] = 70000.0
    elif mutation == "kind":
        space["domains"][0]["kind"] = "float"
    elif mutation == "choice":
        space["domains"][4]["choices"] = ["execute_python"]
    elif mutation == "layout":
        space["layout"] = "unknown"
    else:
        space["domains"].append(space["domains"][0])
    with pytest.raises(ValueError):
        validate_proposal(config, ExpandedProposal.model_validate(raw))


def test_discrete_inclusive():
    d = Domain(path="count", kind="int", low=1.0, high=4.0, choices=[])
    assert [d.sample(x) for x in [0, 0.25, 0.5, 0.99999, 1]] == [1, 2, 3, 4, 4]
    with pytest.raises(ValueError):
        Domain(path="count", kind="int", low=1.2, high=4.0, choices=[])


def test_fixed_endpoint_guard(config):
    raw = config.model_dump()
    raw["endpoint_policy"] = "fixed"
    with pytest.raises(ValueError, match="endpoints"):
        ExpandedConfig.model_validate(raw)


@pytest.mark.parametrize("mode", ["random", "sobol", "mixed"])
def test_real_exports_reproducible(config, tmp_path, mode):
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        root.mkdir()
    suites = [
        compile_scenes(config, demo(config), root, samples=8, seed=13, mode=mode) for root in roots
    ]
    a, b = [s["scenes"] for s in suites]
    assert [(s["parameters"], s["status"], s.get("revision")) for s in a] == [
        (s["parameters"], s["status"], s.get("revision")) for s in b
    ]
    ready = [s for s in a if s["status"] == "READY_FOR_TERRAIN_RUNNER"]
    assert ready
    for row in ready:
        spec = validate_bundle(Path(row["bundle"]), "sha256:" + row["revision"])
        assert spec.goal_xy == tuple(row["goal_xy"])
        assert type(row["parameters"]["seed"]) is int
    assert len(a) == 8
    assert all("robot_failure" not in s for s in a)
    if mode == "mixed":
        assert {s["layout"] for s in a if s["sampler"] == "new_space"} == {
            x.name for x in config.layouts
        }


def test_verified_failure_neighborhood(config, tmp_path):
    layout = config.layouts[0]
    values = {d.path: d.sample(0.5) for d in layout.domains}
    observation = {
        "job_id": "synthetic_fixture",
        "robot_failure": True,
        "status": "EVALUATED",
        "execution_signature": "fixture",
        "layout": layout.name,
        "parameters": values,
        "scene_revision": "fixture",
    }
    suite = compile_scenes(config, demo(config), tmp_path, samples=4, observations=[observation])
    last = suite["scenes"][3]
    assert last["sampler"] == "failure_neighborhood"
    assert last["parent_failure_job"] == "synthetic_fixture"
    for d in layout.domains:
        if d.kind == "float":
            assert (
                abs(last["parameters"][d.path] - values[d.path]) <= (d.high - d.low) * 0.15 + 1e-9
            )


def test_default_cli_no_network_even_with_key(tmp_path):
    import os

    result = subprocess.run(
        [sys.executable, "tools/run_expanded_afs.py", "--output-root", str(tmp_path)],
        cwd=PROJECT,
        env={**os.environ, "OPENAI_API_KEY": "not-a-real-key"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    root = next(tmp_path.iterdir())
    assert json.loads((root / "status.json").read_text())["api_calls"] == 0
    assert not (root / "suite.json").exists()
    assert "not-a-real-key" not in (root / "request.json").read_text()
