import json
import os
from pathlib import Path

import httpx
import pytest

from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.debug_log import CURRENT, Journal
from robot_vlm.timing import RequestTiming


@pytest.mark.parametrize("value", [0, -1, 301, float("nan"), float("inf")])
def test_invalid_timeout(value):
    with pytest.raises(ValueError):
        RequestTiming(value)


def test_coordinated_deadline():
    assert RequestTiming().read_s == 90
    assert RequestTiming().deadline_s == 120
    assert RequestTiming(60).deadline_s == 90


def test_http_timeout_propagation_and_failed_phase_survives_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-secret")
    journal = Journal(tmp_path / "trace.jsonl", 0, read_timeout_s=90)
    token = CURRENT.set(journal)
    seen = []

    def handler(req):
        seen.append(req)
        assert req.extensions["timeout"] == {"read": 90, "connect": 10, "write": 10, "pool": 5}
        req.extensions["trace"]("http11.receive_response_headers.failed", {})
        req.extensions["trace"]("http11.response_closed.complete", {})
        raise httpx.ReadTimeout("mock failure", request=req)

    try:
        with pytest.raises(DiagnosticError) as caught:
            call({"model": "gpt-6-astra"}, lambda x: x, transport=httpx.MockTransport(handler))
        d = caught.value.diagnostic
        assert d["http_timeout_s"] == 90
        assert d["failed_transport_event"] == "http11.receive_response_headers.failed"
        assert d["last_transport_event"] == "http11.response_closed.complete"
        assert len(seen) == 1
    finally:
        CURRENT.reset(token)


@pytest.mark.skipif(os.getenv("RUN_ROBOT_TIMEOUT_GPU") != "1", reason="explicit 32s GPU delay test")
def test_response_after_old_30s_limit_is_accepted():
    import time
    from datetime import datetime, timezone

    from robot_vlm.goal_policy import GoalAction
    from robot_vlm.goal_runner import run
    from robot_vlm.push_policy import PushMock

    class Delayed(PushMock):
        def decide(self, obs, png):
            time.sleep(32)
            return GoalAction(
                state_version=obs.state_version,
                plan_summary="MOCK delayed stop",
                action="stop",
                target_xy_m=None,
                skill_request=None,
                vx_mps=0.0,
                vy_mps=0.0,
                yaw_rate_rps=0.0,
                duration_s=0.2,
            ), {"origin": "mock_delayed"}

    root = Path("/workspace/g1_failure/runtime/robot_timeout_checks") / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True)
    print("TIMEOUT_SMOKE=", root, flush=True)
    result = run(
        root,
        Path("/workspace/g1_failure/src/GR00T-WholeBodyControl"),
        Delayed(),
        max_calls=1,
        max_seconds=90,
        enable_push=True,
    )
    assert result["valid_execution"] and result["reason"] == "POLICY_STOP"
    actions = [
        json.loads(line)
        for line in (root / "decisions.jsonl").read_text().splitlines()
        if '"action"' in line
    ]
    assert actions[0]["latency_s"] >= 32 and actions[0]["execution"] == "accepted"
    protocol = json.loads((root / "protocol.json").read_text())
    assert protocol["http_read_timeout_s"] == 90 and protocol["response_deadline_wall_s"] == 120
