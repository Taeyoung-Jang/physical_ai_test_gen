"""Offline API transport audit. No requests, renderer, robot or archive writes."""

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from failure_client.evaluation.goal_run_reader import _constant, _pairs, read_json
from llm_afs.behavior import verified_files

SOURCE = Path(__file__).resolve().parents[1] / "src" / "robot_vlm"
BUILDERS = {
    "policy": "goal_policy.py",
    "observation_contract": "policy.py",
    "wire_contract": "wire_contract.py",
    "execution_feedback": "execution_feedback.py",
    "navigation_tools": "navigation_tools.py",
    "navigation_completion": "navigation_completion.py",
    "task_outcome": "task_outcome.py",
}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def first_request(root, files, protocol):
    """First-call reconstruction only, never claim captured on-wire request identity."""
    required = {"observation_000.json", "goal_context_000.json", "camera_000.png"}
    if not required <= files.keys():
        return {"status": "UNAVAILABLE", "reason": "missing_bound_first_call_inputs"}
    builders = {
        **BUILDERS,
        **({"push_policy": "push_policy.py"} if protocol.get("push_enabled") else {}),
    }
    changed = [
        key
        for key, name in builders.items()
        if protocol.get("source_hashes", {}).get(key) != sha((SOURCE / name).read_bytes())
    ]
    if changed:
        return {
            "status": "UNAVAILABLE",
            "reason": "request_builder_source_mismatch",
            "sources": changed,
        }
    from robot_vlm.goal_policy import GoalPolicy
    from robot_vlm.policy import Observation
    from robot_vlm.push_policy import PushPolicy

    observation = Observation.model_validate(read_json(files["observation_000.json"]))
    context = read_json(files["goal_context_000.json"])
    if observation.state_version != 0 or context["observation_version"] != 0:
        raise ValueError("first call input version mismatch")
    if context["task_contract"] != protocol["task_contract"]:
        raise ValueError("first call task contract mismatch")
    policy = (PushPolicy if protocol.get("push_enabled") else GoalPolicy)(model=protocol["model"])
    policy.task_contract = context["task_contract"]
    policy.navigation_completion = context["navigation_completion"]
    policy.goal_progress = context["goal_progress"]
    png = files["camera_000.png"].read_bytes()
    body = policy.body(observation, png)
    text = body["input"][0]["content"][0]["text"]
    decoded = json.loads(text)
    if decoded["execution_feedback"] != context["execution_feedback"]:
        raise ValueError("first call execution feedback reconstruction mismatch")
    # HTTPX's JSON encoder is compact UTF-8; this is an estimated body, not a wire capture.
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return {
        "status": "SOURCE_BOUND_RECONSTRUCTION",
        "claim": "Reconstructed from bound first-call inputs, not captured request or token count",
        "httpx_style_body_bytes": len(encoded),
        "reconstructed_body_sha256": sha(encoded),
        "context_utf8_bytes": len(text.encode()),
        "image_png_bytes": len(png),
        "image_data_url_chars": len(body["input"][0]["content"][1]["image_url"]),
        "schema_utf8_bytes": len(json.dumps(body["text"]["format"]["schema"]).encode()),
        "reasoning": body["reasoning"],
        "image_detail": body["input"][0]["content"][1]["detail"],
        "output_token_cap_present": "max_output_tokens" in body,
        "geometry_objects": len(observation.geometry),
        "history_items": len(policy.memory),
    }


def call_summary(path, version):
    rows = [
        json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("empty API journal")
    for row in rows:
        elapsed = row.get("elapsed_wall_s")
        if (
            row.get("observation_version") != version
            or type(elapsed) not in (int, float)
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("invalid API journal version/time")
    if any(a["elapsed_wall_s"] > b["elapsed_wall_s"] for a, b in zip(rows, rows[1:])):
        raise ValueError("nonmonotonic API journal")
    events = {
        r.get("transport_event"): r["elapsed_wall_s"] for r in rows if r.get("event") == "transport"
    }
    terminal = next(
        (r for r in reversed(rows) if r.get("event") in {"api_failed", "api_completed"}), {}
    )
    diag = terminal.get("diagnostic") or {}
    failed = diag.get("failed_transport_event") or next(
        (e for e in reversed(events) if e and e.endswith(".failed")), None
    )
    phase = "unknown"
    if failed:
        if "receive_response_headers" in failed:
            phase = "response_headers"
        elif "receive_response_body" in failed:
            phase = "response_body"
        elif "send_request" in failed:
            phase = "request_write"
        elif "connect_tcp" in failed or "start_tls" in failed:
            phase = "connection_or_tls"
    started = next((r for r in rows if r.get("event") == "api_started"), {})
    ids = {r.get("client_request_id") for r in rows}
    if len(ids) != 1:
        raise ValueError("mixed request IDs in journal")
    client_id = next(iter(ids))
    if not isinstance(client_id, str) or not re.fullmatch(r"[a-fA-F0-9-]{36}", client_id):
        client_id = None
    sent = next(
        (t for e, t in events.items() if e and e.endswith("send_request_body.complete")), None
    )
    end = terminal.get("elapsed_wall_s")
    headers = next((r for r in rows if r.get("event") == "response_headers"), {})
    return {
        "observation_version": version,
        "client_request_id": client_id,
        "terminal_event": terminal.get("event"),
        "code": diag.get("code"),
        "failed_phase": phase,
        "request_body_sent": sent is not None,
        "response_headers_received": bool(headers),
        "http_status": headers.get("http_status"),
        "request_id": headers.get("request_id"),
        "timeout_s": started.get("timeout_s"),
        "reasoning": started.get("reasoning"),
        "elapsed_wall_s": end,
        "wait_after_send_s": end - sent if end is not None and sent is not None else None,
        "usage": diag.get("usage"),
        "retry_attempted": diag.get("retry_attempted"),
        "support_note": (
            "Client request ID permits provider-side investigation; "
            "local logs do not prove receipt or cause"
        ),
    }


def audit_run(root):
    root = Path(root).resolve()
    files = verified_files(root)
    protocol = read_json(files["protocol.json"])
    calls = []
    for name, path in sorted(files.items()):
        matched = re.fullmatch(r"api_call_(\d{3,})\.jsonl", name)
        if matched:
            calls.append(call_summary(path, int(matched[1])))
    result = read_json(files["result.json"])
    return {
        "run": str(root),
        "verified_artifacts": len(files),
        "source_manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "task_outcome": result.get("task_outcome"),
        "model": protocol.get("model"),
        "recorded_robot_condition": result.get("robot_condition_sha256"),
        "termination_reason": result.get("reason"),
        "live_actions_accepted": result.get("live_actions_accepted"),
        "calls": calls,
        "first_request": first_request(root, files, protocol),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    output = args.output_dir or Path(
        "/workspace/g1_failure/runtime/robot_api_audit"
    ) / datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    roots = [p.resolve() for p in args.run]
    if any(output.resolve().is_relative_to(p) or p.is_relative_to(output.resolve()) for p in roots):
        parser.error("output must be disjoint from input archives")
    report = {
        "schema_version": "offline-robot-api-audit-v1",
        "new_api_calls": 0,
        "runs": [audit_run(p) for p in roots],
        "limits": [
            "Bytes are not tokens or a demonstrated latency cause",
            "No timeout/model/reasoning changes, retries, goal verdict edits or budget resets",
            "First-call reconstruction only; no raw request, image or credentials exported",
        ],
    }
    report["tool_sha256"] = sha(Path(__file__).read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
    )
    (output / "report.html").write_text(
        "<!doctype html><meta charset='utf-8'><h1>Offline robot API audit</h1><pre>"
        + escape(json.dumps(report, indent=2, ensure_ascii=False))
        + "</pre>"
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-api-audit-artifacts-v1",
                "artifacts": [
                    {"path": name, "sha256": sha((output / name).read_bytes())}
                    for name in ("audit.json", "report.html")
                ],
            },
            indent=2,
        )
    )
    print(f"ROBOT_API_AUDIT={output}; REPORT={output / 'report.html'}; no API/robot executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
