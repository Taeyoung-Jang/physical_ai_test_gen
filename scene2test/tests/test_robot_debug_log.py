import json
from types import SimpleNamespace

import httpx
import pytest

from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.debug_log import CURRENT, Journal


@pytest.mark.parametrize("mode", ["timeout", "http", "ok", "unexpected"])
def test_flushed_trace_redaction_and_failure_details(tmp_path, monkeypatch, mode):
    secret = "sk-test-secret-debug"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    journal = Journal(tmp_path / "api_call_000.jsonl", 7)

    def handler(req):
        assert req.headers["X-Client-Request-Id"] == journal.client_request_id
        req.extensions["trace"]("connection.connect_tcp.started", {})
        assert journal.path.exists()
        if mode == "timeout":
            raise httpx.ReadTimeout("waiting " + secret, request=req)
        if mode == "unexpected":
            raise RuntimeError("internal " + secret)
        if mode == "http":
            return httpx.Response(
                400,
                json={"error": {"message": "bad schema " + secret, "code": "invalid_json_schema"}},
                headers={"x-request-id": "req_debug"},
            )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"ok": true}'}],
                    }
                ],
            },
        )

    class Policy:
        def decide(self, obs, png):
            return call(
                {"model": "gpt-6-astra"}, lambda x: x, transport=httpx.MockTransport(handler)
            )

    if mode == "ok":
        assert journal.decide(Policy(), SimpleNamespace(), b"")[0] == {"ok": True}
    else:
        with pytest.raises((DiagnosticError, RuntimeError)):
            journal.decide(Policy(), SimpleNamespace(), b"")
    text = journal.path.read_text()
    assert secret not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert rows[-1]["event"] == ("policy_completed" if mode == "ok" else "policy_failed")
    assert all(r["observation_version"] == 7 for r in rows)
    assert all(r["elapsed_wall_s"] >= 0 for r in rows)
    if mode == "timeout":
        d = rows[-1]["diagnostic"]
        assert d["last_transport_event"] == "connection.connect_tcp.started"
        assert d["exception_chain"][0]["frames"]
    if mode == "http":
        assert rows[-1]["diagnostic"]["request_id"] == "req_debug"
        assert "bad schema" in rows[-1]["diagnostic"]["api_error_message"]
    assert CURRENT.get() is None
