"""No real API, network, sleeping, simulation or robot needed."""

import json

import httpx
import pytest

from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.debug_log import CURRENT, Journal


def success():
    return httpx.Response(
        200,
        json={
            "id": "resp_test",
            "status": "completed",
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "{}"}],
                }
            ],
        },
    )


def invoke(tmp_path, monkeypatch, handler):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-retry-secret")
    sleeps = []
    monkeypatch.setattr("robot_vlm.api_transport.time.sleep", sleeps.append)
    journal = Journal(tmp_path / "trace.jsonl", 3, read_timeout_s=300, connect_retries=2)
    token = CURRENT.set(journal)
    try:
        result = call({"model": "unchanged"}, lambda x: x, transport=httpx.MockTransport(handler))
        return result, sleeps, journal.path
    finally:
        CURRENT.reset(token)


@pytest.mark.parametrize("exception", [httpx.ConnectError, httpx.ConnectTimeout])
def test_two_pre_send_failures_then_success(tmp_path, monkeypatch, exception):
    requests = []

    def handler(req):
        requests.append(req)
        if len(requests) <= 2:
            req.extensions["trace"]("connection.connect_tcp.failed", {})
            raise exception("sk-retry-secret", request=req)
        return success()

    (_, meta), sleeps, log = invoke(tmp_path, monkeypatch, handler)
    d = meta["diagnostic"]
    assert len(requests) == 3 and sleeps == [1, 2]
    assert len({r.content for r in requests}) == 1
    assert len({r.headers["X-Client-Request-Id"] for r in requests}) == 1
    assert d["connection_attempts"] == 3 and d["retry_count"] == 2
    assert d["retry_attempted"] and len(d["connection_failures"]) == 2
    assert meta["usage"] == {"input_tokens": 5, "output_tokens": 2}
    assert "sk-retry-secret" not in log.read_text() + json.dumps(d)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(r["event"] == "connection_retry_scheduled" for r in rows) == 2


def test_third_connection_failure_stops(tmp_path, monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        req.extensions["trace"]("connection.connect_tcp.failed", {})
        raise httpx.ConnectError("DNS unavailable", request=req)

    with pytest.raises(DiagnosticError) as err:
        invoke(tmp_path, monkeypatch, handler)
    assert len(seen) == 3
    assert err.value.diagnostic["retry_count"] == 2
    assert len(err.value.diagnostic["connection_failures"]) == 3
    assert err.value.diagnostic["connection_failures"][-1]["retry_scheduled"] is False


@pytest.mark.parametrize("kind", ["unknown", "tls", "sent", "read", "write", "http500"])
def test_ambiguous_or_post_send_never_retried(tmp_path, monkeypatch, kind):
    seen = []

    def handler(req):
        seen.append(req)
        trace = req.extensions["trace"]
        if kind == "http500":
            return httpx.Response(500)
        if kind == "sent":
            trace("http11.send_request_headers.started", {})
            trace("connection.connect_tcp.failed", {})
        elif kind == "tls":
            trace("connection.start_tls.failed", {})
        if kind == "read":
            raise httpx.ReadTimeout("ambiguous", request=req)
        if kind == "write":
            raise httpx.WriteError("ambiguous", request=req)
        raise httpx.ConnectError("not proven pre-send", request=req)

    with pytest.raises(DiagnosticError) as err:
        invoke(tmp_path, monkeypatch, handler)
    assert len(seen) == 1 and err.value.diagnostic["retry_count"] == 0


def test_failure_after_retry_does_not_reuse_previous_trace(tmp_path, monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        if len(seen) == 1:
            req.extensions["trace"]("connection.connect_tcp.failed", {})
        raise httpx.ConnectError("second failure without trace", request=req)

    with pytest.raises(DiagnosticError):
        invoke(tmp_path, monkeypatch, handler)
    assert len(seen) == 2


def test_recorded_response_header_timeout_is_not_a_connection_retry(tmp_path, monkeypatch):
    """Replay the observed transport event order without a network call or 300s wait."""
    seen = []

    def handler(req):
        seen.append(req)
        trace = req.extensions["trace"]
        for event in (
            "connection.connect_tcp.started",
            "connection.connect_tcp.complete",
            "connection.start_tls.complete",
            "http11.send_request_headers.started",
            "http11.send_request_headers.complete",
            "http11.send_request_body.complete",
            "http11.receive_response_headers.started",
            "http11.receive_response_headers.failed",
        ):
            trace(event, {})
        raise httpx.ReadTimeout("The read operation timed out", request=req)

    with pytest.raises(DiagnosticError) as err:
        invoke(tmp_path, monkeypatch, handler)
    assert len(seen) == 1
    d = err.value.diagnostic
    assert d["code"] == "api_timeout" and d["exception_type"] == "ReadTimeout"
    assert d["failed_transport_event"] == "http11.receive_response_headers.failed"
    assert d["max_connect_retries"] == 2 and d["retry_count"] == 0
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert not any(r["event"] == "connection_retry_scheduled" for r in rows)


@pytest.mark.parametrize("value", [-1, 3, 1.0, True])
def test_invalid_connect_retry_limits_refused_before_dispatch(tmp_path, value):
    with pytest.raises(ValueError, match="connect_retries"):
        Journal(tmp_path / "unused.jsonl", 0, read_timeout_s=300, connect_retries=value)
    assert not (tmp_path / "unused.jsonl").exists()
