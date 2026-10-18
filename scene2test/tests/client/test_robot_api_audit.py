"""Read-only transport analysis, never a paid API or robot test."""

import json
import runpy

import httpx
import pytest

from robot_vlm.execution_feedback import policy_feedback
from robot_vlm.goal_policy import GoalPolicy
from tests.test_robot_vlm import PNG, obs

from .test_afs_contrast import source
from .test_behavior_memory import _rebind
from .test_discovery_measures import json_write


@pytest.fixture
def tool():
    return runpy.run_path("tools/audit_robot_api.py")


def journal(path, *, failed="http11.receive_response_headers.failed", headers=False):
    rows = [
        {"event": "api_started", "timeout_s": 300, "reasoning": {"effort": "high"}},
        {"event": "transport", "transport_event": "http11.send_request_body.complete"},
    ]
    if headers:
        rows.append({"event": "response_headers", "http_status": 200, "request_id": "req_test"})
    rows.extend(
        [
            {"event": "transport", "transport_event": failed},
            {"event": "transport", "transport_event": "http11.response_closed.complete"},
            {
                "event": "api_failed",
                "diagnostic": {"code": "api_timeout", "retry_attempted": False},
            },
        ]
    )
    for index, row in enumerate(rows):
        row.update(
            elapsed_wall_s=float(index),
            observation_version=0,
            client_request_id="00000000-0000-0000-0000-000000000000",
        )
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return rows


def test_timeout_phase_survives_transport_cleanup(tool, tmp_path):
    path = tmp_path / "journal"
    journal(path)
    result = tool["call_summary"](path, 0)
    assert result["failed_phase"] == "response_headers"
    assert result["request_body_sent"] and not result["response_headers_received"]
    assert result["usage"] is None and result["retry_attempted"] is False
    journal(path, failed="http11.receive_response_body.failed", headers=True)
    assert tool["call_summary"](path, 0)["failed_phase"] == "response_body"


@pytest.mark.parametrize("bad", ["version", "time", "ids"])
def test_bad_journal_rejected(tool, tmp_path, bad):
    path = tmp_path / "journal"
    rows = journal(path)
    rows[-1][
        {"version": "observation_version", "time": "elapsed_wall_s", "ids": "client_request_id"}[
            bad
        ]
    ] = (999 if bad == "version" else -1) if bad != "ids" else "changed"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError):
        tool["call_summary"](path, 0)


def fixture(tool, tmp_path):
    root = source(tmp_path / "archive")
    observation = obs().model_copy(update={"state_version": 0})
    policy = GoalPolicy(model="synthetic")
    context = {
        "observation_version": 0,
        "task_contract": policy.task_contract,
        "navigation_completion": policy.navigation_completion,
        "goal_progress": None,
        "execution_feedback": policy_feedback([], observation.yaw_rad),
    }
    json_write(root / "observation_000.json", observation.model_dump())
    json_write(root / "goal_context_000.json", context)
    (root / "camera_000.png").write_bytes(PNG)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol.update(model="synthetic", push_enabled=False, task_contract=policy.task_contract)
    protocol["source_hashes"].update(
        {
            key: tool["sha"]((tool["SOURCE"] / name).read_bytes())
            for key, name in tool["BUILDERS"].items()
        }
    )
    json_write(root / "protocol.json", protocol)
    journal(root / "api_call_000.jsonl")
    _rebind(root)
    return root


def test_bound_request_comparison_no_network_or_archive_mutation(tool, tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("network/client forbidden")

    monkeypatch.setattr(httpx, "Client", forbidden)
    root = fixture(tool, tmp_path)
    before = {p.name: tool["sha"](p.read_bytes()) for p in root.iterdir() if p.is_file()}
    output = tmp_path / "audit"
    assert tool["main"](["--run", str(root), "--output-dir", str(output)]) == 0
    after = {p.name: tool["sha"](p.read_bytes()) for p in root.iterdir() if p.is_file()}
    assert before == after
    report = json.loads((output / "audit.json").read_text())
    request = report["runs"][0]["first_request"]
    assert request["status"] == "SOURCE_BOUND_RECONSTRUCTION"
    assert request["reasoning"] == {"effort": "high"}
    assert request["image_detail"] == "high" and not request["output_token_cap_present"]
    assert request["history_items"] == 0 and report["new_api_calls"] == 0
    assert "data:image/png;base64" not in (output / "audit.json").read_text()
    with pytest.raises(FileExistsError):
        tool["main"](["--run", str(root), "--output-dir", str(output)])


def test_source_drift_refuses_reconstruction(tool, tmp_path):
    root = fixture(tool, tmp_path)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol["source_hashes"]["policy"] = "wrong"
    json_write(root / "protocol.json", protocol)
    _rebind(root)
    assert tool["audit_run"](root)["first_request"]["reason"] == "request_builder_source_mismatch"


def test_tamper_and_output_overlap_refused(tool, tmp_path):
    root = fixture(tool, tmp_path)
    with pytest.raises(SystemExit):
        tool["main"](["--run", str(root), "--output-dir", str(root / "audit")])
    (root / "observation_000.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact mismatch"):
        tool["audit_run"](root)
