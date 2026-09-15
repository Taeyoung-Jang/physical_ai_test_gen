"""No network or GPU calls: provider mock, real geometry exports, synthetic feedback."""

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml

from llm_afs.contracts import Config, Proposal, context, proposal_schema, validate_proposal
from llm_afs.provider import call, extract_proposal, request_body
from llm_afs.workflow import compile_scenes, demo_proposal, digest, import_feedback, read, write
from procedural_world.terrain import generate_course
from simulation_server.worlds import validate_bundle


@pytest.fixture(scope="module")
def config():
    return Config.model_validate(
        yaml.safe_load((Path(__file__).parents[1] / "config/llm_afs_terrain.yaml").read_text())
    )


def response(value):
    return {
        "id": "resp_fixture",
        "status": "completed",
        "model": "gpt-6-astra",
        "usage": {"input_tokens": 12, "output_tokens": 34},
        "output": [
            {"type": "reasoning"},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(value)}],
            },
        ],
    }


def test_structured_request_and_mock_api(config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-a-real-key")
    proposal = demo_proposal(config).model_dump()
    body = request_body(context(config), proposal_schema(config))
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert json.loads(request.content)["text"]["format"]["strict"] is True
        return httpx.Response(200, json=response(proposal))

    result = call(body, transport=httpx.MockTransport(handler))
    assert extract_proposal(result) == proposal
    assert len(requests) == 1
    assert body["store"] is False and body["model"] == "gpt-6-astra"
    assert "test-placeholder" not in json.dumps(body)
    assert validate_proposal(config, Proposal.model_validate(proposal))


def test_missing_key_fails_without_network(config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        call({})


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_api_errors_no_retry_or_secret_leak(monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="test-placeholder secret body")

    with pytest.raises(RuntimeError, match=f"HTTP {status}") as exc:
        call({}, transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert "test-placeholder" not in str(exc.value)


@pytest.mark.parametrize(
    "value",
    [
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": []},
        {
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal"}]}],
        },
    ],
)
def test_incomplete_refusal_missing_rejected(value):
    with pytest.raises(ValueError):
        extract_proposal(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "revision",
        "unknown",
        "outside",
        "duplicate",
        "candidate_missing",
        "candidate_outside",
        "extra",
        "nan",
    ],
)
def test_invalid_proposals_rejected(config, mutation):
    p = demo_proposal(config).model_dump()
    if mutation == "revision":
        p["base_scene_revision"] = "wrong"
    elif mutation == "unknown":
        p["ranges"][0]["path"] = "planning_max_slope_deg"
    elif mutation == "outside":
        p["ranges"][0]["high"] = 99.0
    elif mutation == "duplicate":
        p["ranges"].append(p["ranges"][0])
    elif mutation == "candidate_missing":
        p["representatives"][0]["values"].pop()
    elif mutation == "candidate_outside":
        p["representatives"][0]["values"][0]["value"] = 99.0
    elif mutation == "extra":
        p["task_spec"] = {"success": "always"}
    else:
        p["ranges"][0]["low"] = float("nan")
    with pytest.raises(ValueError):
        validate_proposal(config, Proposal.model_validate(p))


def test_schema_all_fields_required_and_closed(config):
    schema = proposal_schema(config)
    for obj in [schema, *schema["$defs"].values()]:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_feedback_changes_next_input_not_predicted_truth(config):
    first = request_body(context(config), proposal_schema(config))
    second = request_body(
        context(config, [{"status": "EVALUATED", "robot_failure": True, "reason": "STUCK"}]),
        proposal_schema(config),
    )
    assert first != second
    assert "STUCK" in second["input"][0]["content"]
    with pytest.raises(ValueError, match="250 KB"):
        request_body({"oversize": "x" * 250001}, proposal_schema(config))


def test_real_bundles_repeatable_preserve_endpoints(config, tmp_path):
    proposal = demo_proposal(config)
    roots = [tmp_path / str(i) for i in range(2)]
    for root in roots:
        root.mkdir()
    a, b = [compile_scenes(config, proposal, root, samples=2, seed=42) for root in roots]
    assert [s["revision"] for s in a["scenes"]] == [s["revision"] for s in b["scenes"]]
    base = generate_course(config.course)
    for row in a["scenes"]:
        spec = validate_bundle(Path(row["bundle"]))
        assert (spec.spawn_xy, spec.goal_xy) == (base.spawn_xy, base.goal_xy)
        assert spec.config.seed == base.config.seed


def test_duplicate_candidates_not_resubmitted(config, tmp_path):
    p = demo_proposal(config).model_dump()
    p["representatives"].append(copy.deepcopy(p["representatives"][0]))
    suite = compile_scenes(config, Proposal.model_validate(p), tmp_path, samples=0)
    assert suite["scenes"][1]["status"] == "DUPLICATE_SCENE"


def test_static_invalid_not_robot_failure(config, tmp_path):
    cfg = config.model_dump()
    cfg["domains"][0]["high"] = 30.0
    cfg = Config.model_validate(cfg)
    p = demo_proposal(cfg).model_dump()
    p["representatives"][0]["values"][0]["value"] = 30.0
    suite = compile_scenes(cfg, Proposal.model_validate(p), tmp_path, samples=0)
    assert suite["scenes"][0]["status"] == "INVALID_SCENE"
    assert "robot_failure" not in suite["scenes"][0]


@pytest.fixture
def feedback(config, tmp_path):
    """Synthetic result contract, NOT evidence of real GPU execution."""
    prior = tmp_path / "prior"
    prior.mkdir()
    suite = compile_scenes(config, demo_proposal(config), prior, samples=0)
    ctx = context(config)
    write(prior / "context.json", ctx)
    write(
        prior / "protocol.json",
        {"config_sha256": digest(config.model_dump()), "context_sha256": digest(ctx)},
    )
    write(prior / "status.json", {"suite_sha256": digest(suite)})
    runner = tmp_path / "runner"
    job = runner / "job_fixture"
    job.mkdir(parents=True)
    task = config.task_spec
    candidate = suite["scenes"][0]
    spec = validate_bundle(Path(candidate["bundle"]))
    write(
        runner / "protocol.json",
        {
            "suite": str(prior / "suite.json"),
            "duration_s": task["maximum_duration_s"],
            "speed_mps": task["speed_mps"],
        },
    )
    request = {
        "resources": {
            "scene": {"id": spec.scene_id, "revision": "sha256:" + spec.revision},
            "robot": {"id": config.robot_spec["id"], "revision": "fixture"},
            "policy": {"id": config.policy_spec["policy_id"], "revision": "fixture"},
        },
        "task": {"schema": "navigation@1.0", "parameters": {"speed_mps": task["speed_mps"]}},
        "execution": {
            "seed": spec.config.seed,
            **{
                k: task[k]
                for k in ["maximum_duration_s", "physics_timestep_s", "settling_duration_s"]
            },
        },
    }
    write(job / "request.json", request)
    facts = {"navigation_success": False, "goal_distance_m": 2.0}
    reproduction = {
        "resolved_resources": request["resources"],
        "scene_revision": spec.revision,
        "runtime": {"execution_provider": "CUDAExecutionProvider"},
        "code_sha256": {"worker.py": "fixture"},
        "source_resource_sha256": {},
        "metrics_version": "fixture",
        "task_facts": facts,
    }
    artifacts = []
    for name, value in [
        ("reproduction.json", reproduction),
        ("scene_spec.json", spec.to_dict()),
        ("state_trajectory.jsonl", {"fixture": True}),
    ]:
        write(job / name, value)
        data = (job / name).read_bytes()
        artifacts.append(
            {
                "artifact_id": f"{job.name}:{name}",
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    result = {
        "job_id": job.name,
        "artifacts": artifacts,
        "task_facts": facts,
        "execution": {"valid": True, "status": "SUCCEEDED", "termination_reason": "STUCK"},
    }
    write(job / "execution_result.json", result)
    write(
        runner / "summary.json",
        [
            {
                "name": candidate["name"],
                "index": candidate["index"],
                "job": str(job),
                "status": "EVALUATED",
            }
        ],
    )
    return prior, runner / "summary.json", job


def test_verified_feedback_import(config, feedback):
    prior, summary, _ = feedback
    rows = import_feedback(config, prior, summary)
    assert rows[0]["robot_failure"] is True
    assert rows[0]["status"] == "EVALUATED"
    assert "execution_signature" in rows[0]


@pytest.mark.parametrize("target", ["artifact", "suite", "context", "task", "facts"])
def test_feedback_tampering_rejected(config, feedback, target):
    prior, summary, job = feedback
    paths = {
        "artifact": job / "state_trajectory.jsonl",
        "suite": prior / "suite.json",
        "context": prior / "context.json",
        "task": job / "request.json",
        "facts": job / "execution_result.json",
    }
    path = paths[target]
    value = read(path)
    if target == "task":
        value["task"]["parameters"]["speed_mps"] = 0.4
    elif target == "facts":
        value["task_facts"]["navigation_success"] = True
    else:
        value["tampered"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        import_feedback(config, prior, summary)


def test_invalid_execution_not_failure(config, feedback):
    prior, summary, job = feedback
    result = read(job / "execution_result.json")
    result["execution"]["valid"] = False
    (job / "execution_result.json").write_text(json.dumps(result))
    rows = import_feedback(config, prior, summary)
    assert rows[0]["status"] == "INDETERMINATE"
    assert rows[0]["robot_failure"] is None
