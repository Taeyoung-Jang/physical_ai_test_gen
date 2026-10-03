"""Manifest-bound observed usage, including completed/incomplete post-stop responses.

No network, price estimates or invented zero costs. Optional corrupt accounting
does not change a robot's goal outcome; conflicting calls are excluded from sums.
"""

import re


def collect_usage(root, hashes, *, max_calls, attempted):
    # Lazy import avoids a cycle with the archive reader.
    from .goal_run_reader import _rows, read_json

    calls, conflicts, warnings = {}, set(), []

    def add(cid, meta, source):
        if not isinstance(meta, dict):
            raise ValueError("invalid_provider")
        diagnostic = meta.get("diagnostic") or {}
        if not isinstance(diagnostic, dict):
            raise ValueError("invalid_diagnostic")
        usage = meta.get("usage")
        if usage is None:
            usage = diagnostic.get("usage")
        if usage is None:
            return
        if type(cid) is not int or not 0 <= cid < max_calls:
            raise ValueError("invalid_call_id")
        if meta.get("usage") is not None and diagnostic.get("usage") is not None:
            if not isinstance(meta["usage"], dict) or not isinstance(diagnostic["usage"], dict):
                conflicts.add(cid)
                raise ValueError("invalid_usage")
            if any(
                meta["usage"].get(k) != diagnostic["usage"].get(k)
                for k in ("input_tokens", "output_tokens")
            ):
                conflicts.add(cid)
        if meta.get("response_id") and diagnostic.get("response_id"):
            if meta["response_id"] != diagnostic["response_id"]:
                conflicts.add(cid)
        if not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")
        ):
            conflicts.add(cid)
            raise ValueError("invalid_usage")
        counts = [usage["input_tokens"], usage["output_tokens"]]
        if "total_tokens" in usage and (
            type(usage["total_tokens"]) is not int or usage["total_tokens"] != sum(counts)
        ):
            conflicts.add(cid)
            raise ValueError("inconsistent_total")
        rid = meta.get("response_id") or diagnostic.get("response_id")
        if rid is not None and (not isinstance(rid, str) or not re.fullmatch(r"[\w-]{1,220}", rid)):
            conflicts.add(cid)
            raise ValueError("invalid_response_id")
        row = calls.setdefault(cid, {"tokens": counts, "response_id": rid, "evidence": []})
        if row["tokens"] != counts or (rid and row["response_id"] and rid != row["response_id"]):
            conflicts.add(cid)
        row["response_id"] = row["response_id"] or rid
        row["evidence"].append(source)

    def guarded(cid, meta, source):
        try:
            add(cid, meta, source)
        except (ValueError, TypeError, KeyError) as exc:
            warnings.append(f"{source['artifact']}:{type(exc).__name__}")

    for name in sorted(hashes):
        if name not in {"decisions.jsonl", "pending_call.json"} and not re.fullmatch(
            r"api_call_\d{3}\.jsonl", name
        ):
            continue
        try:
            rows = [read_json(root / name)] if name.endswith(".json") else _rows(root / name)
            for line, row in enumerate(rows, 1):
                ref = {"artifact": name, "sha256": hashes[name], "line": line}
                if name == "decisions.jsonl" and "action" in row:
                    guarded(row.get("observation_version"), row.get("provider", {}), ref)
                elif name == "pending_call.json":
                    guarded(row.get("observation_version"), row.get("provider", {}), ref)
                elif name.startswith("api_call_"):
                    cid = row.get("observation_version")
                    if cid != int(name[9:12]) or type(cid) is not int:
                        raise ValueError("journal_call_id_mismatch")
                    guarded(cid, {"diagnostic": row.get("diagnostic")}, ref)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            warnings.append(name + ":malformed_usage_source")
    by_response = {}
    for cid, row in calls.items():
        rid = row["response_id"]
        if rid:
            if rid in by_response and by_response[rid] != cid:
                conflicts.update((cid, by_response[rid]))
            by_response[rid] = cid
    if conflicts:
        warnings.append("conflicting_call_usage_excluded")
    accepted = [
        {
            "call_id": cid,
            "input_tokens": row["tokens"][0],
            "output_tokens": row["tokens"][1],
            "response_id": row["response_id"],
            "evidence": row["evidence"],
        }
        for cid, row in sorted(calls.items())
        if cid not in conflicts
    ]
    missing = max(0, attempted - len(accepted))
    if missing:
        warnings.append("calls_without_observed_usage")
    if len(accepted) > attempted:
        warnings.append("observed_usage_exceeds_declared_api_calls")
    return {
        "schema_version": "robot-call-usage-v2",
        "status": "PARTIAL" if warnings else "OBSERVED" if accepted else "UNAVAILABLE",
        "calls": accepted,
        "conflicting_call_ids": sorted(conflicts),
        "calls_missing_usage": missing,
        "warnings": sorted(set(warnings)),
        "claim": "Provider-observed tokens, not a bill; missing costs are unknown, not zero",
    }
