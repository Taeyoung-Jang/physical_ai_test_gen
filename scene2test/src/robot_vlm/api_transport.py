"""Categorized, secret-safe API diagnostics; no retries or raw response persistence."""

import hashlib
import json
import os
import re
import time
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .debug_log import CURRENT, clean, exception_detail
from .policy import PolicyError


class DiagnosticError(PolicyError):
    def __init__(self, code, diagnostic):
        super().__init__(code)
        self.diagnostic = {**diagnostic, "code": code}


def call(body, parse, *, transport=None):
    started = time.monotonic()
    journal = CURRENT.get()
    read_timeout = journal.read_timeout_s if journal else 30.0
    client_id = journal.client_request_id if journal else str(uuid4())
    key = os.getenv("OPENAI_API_KEY")
    info = {
        "stage": "credentials",
        "retry_attempted": False,
        "client_request_id": client_id,
        "http_timeout_s": read_timeout,
        "http_timeouts_s": {"read": read_timeout, "connect": 10, "write": 10, "pool": 5},
    }

    def emit(event, **fields):
        if journal:
            journal.emit(event, **fields)

    def fail(code):
        info["elapsed_wall_s"] = time.monotonic() - started
        emit("api_failed", diagnostic={**info, "code": code})
        raise DiagnosticError(code, info)

    if not key:
        fail("missing_api_key")

    def identifier(value, pattern):
        return (
            value
            if isinstance(value, str) and key not in value and re.fullmatch(pattern, value)
            else None
        )

    info["stage"] = "transport"
    emit(
        "api_started",
        model=body.get("model"),
        timeout_s=read_timeout,
        reasoning=body.get("reasoning"),
        max_output_tokens=body.get("max_output_tokens"),
    )

    def trace(event, details):
        info["last_transport_event"] = event
        if event.endswith(".failed"):
            info["failed_transport_event"] = event
        emit("transport", transport_event=event)

    def received(response):
        info["http_status"] = response.status_code
        info["request_id"] = identifier(
            response.headers.get("x-request-id"), r"[A-Za-z0-9_-]{1,200}"
        )
        emit("response_headers", http_status=response.status_code, request_id=info["request_id"])

    try:
        with httpx.Client(
            timeout=httpx.Timeout(read_timeout, connect=10, write=10, pool=5),
            transport=transport,
            follow_redirects=False,
            event_hooks={"response": [received]},
        ) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                json=body,
                headers={"Authorization": f"Bearer {key}", "X-Client-Request-Id": client_id},
                extensions={"trace": trace},
            )
    except httpx.TimeoutException as exc:
        info["exception_type"] = type(exc).__name__
        info["exception_chain"] = exception_detail(exc)
        fail("api_timeout")
    except httpx.HTTPError as exc:
        info["exception_type"] = type(exc).__name__
        info["exception_chain"] = exception_detail(exc)
        fail("api_transport_error")
    info.update(
        {
            "stage": "http",
            "http_status": response.status_code,
            "request_id": identifier(response.headers.get("x-request-id"), r"[A-Za-z0-9_-]{1,200}"),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "response_bytes": len(response.content),
        }
    )
    if response.status_code != 200:
        try:
            error = response.json().get("error", {})
            known = {
                "invalid_api_key",
                "invalid_request_error",
                "rate_limit_exceeded",
                "insufficient_quota",
                "model_not_found",
                "context_length_exceeded",
                "invalid_json_schema",
                "server_error",
                "permission_denied",
                "unsupported_value",
                "invalid_value",
                "authentication_error",
            }
            if isinstance(error, dict):
                info["api_error_message"] = clean(error.get("message", ""))
                info["api_error_param"] = clean(error.get("param", ""))
                for name in ("code", "type"):
                    candidate = error.get(name)
                    if isinstance(candidate, str) and candidate in known:
                        info["api_error_" + name] = candidate
        except (ValueError, AttributeError):
            pass
        fail(f"api_http_{response.status_code}")
    info["stage"] = "response_json"
    try:
        value = response.json()
    except ValueError:
        fail("response_json_error")
    if not isinstance(value, dict):
        fail("response_shape_error")
    info["response_id"] = identifier(value.get("id"), r"resp_[A-Za-z0-9_-]{1,200}")
    usage = value.get("usage")
    info["usage"] = (
        {
            k: v
            for k, v in usage.items()
            if k in {"input_tokens", "output_tokens", "total_tokens"} and type(v) is int and v >= 0
        }
        if isinstance(usage, dict)
        else None
    )
    info["stage"] = "response_status"
    if value.get("status") != "completed":
        details = value.get("incomplete_details") or {}
        code = details.get("reason") if isinstance(details, dict) else None
        info["incomplete_reason"] = (
            code if code in {"max_output_tokens", "content_filter"} else None
        )
        fail("api_incomplete_response")
    info["stage"] = "response_content"
    texts = []
    output = value.get("output")
    if not isinstance(output, list):
        fail("response_shape_error")
    for item in output:
        if not isinstance(item, dict):
            fail("response_shape_error")
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            fail("response_shape_error")
        for part in contents:
            if not isinstance(part, dict):
                fail("response_shape_error")
            if part.get("type") == "refusal":
                fail("api_refusal")
            if part.get("type") == "output_text":
                if not isinstance(part.get("text"), str):
                    fail("response_shape_error")
                texts.append(part["text"])
    if len(texts) != 1:
        fail("response_ambiguous_output")
    info["stage"] = "action_json"
    info["action_text_excerpt"] = clean(texts[0])
    try:
        payload = json.loads(texts[0])
    except ValueError:
        fail("action_json_error")
    info["stage"] = "action_validation"
    try:
        action = parse(payload)
    except ValidationError as exc:
        allowed = {
            "command",
            "Navigate",
            "Move",
            "Passive",
            "Skill",
            "VelocityMove",
            "VelocityPassive",
            "action",
            "state_version",
            "plan_summary",
            "target_xy_m",
            "skill_request",
            "vx_mps",
            "vy_mps",
            "yaw_rate_rps",
            "duration_s",
        }
        info["validation_errors"] = [
            {
                "type": e["type"],
                "location": [p if type(p) is int or p in allowed else "<field>" for p in e["loc"]],
            }
            for e in exc.errors(include_url=False, include_context=False, include_input=False)
        ][:32]
        fail("action_schema_error")
    except (TypeError, KeyError, ValueError):
        fail("action_decode_error")
    info.pop("action_text_excerpt", None)
    info["stage"] = "completed"
    info["elapsed_wall_s"] = time.monotonic() - started
    emit("api_completed", diagnostic=info)
    return action, {
        "response_id": info.get("response_id"),
        "model": identifier(value.get("model"), r"[A-Za-z0-9_.:-]{1,100}"),
        "requested_model": body["model"],
        "usage": info["usage"],
        "origin": "openai_api",
        "diagnostic": info,
    }
