"""Read-only goal-agent-v5 importer. No simulator, policy calls or inferred failure labels."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from robot_vlm.task_outcome import GoalEvaluator, digest, task_contract

from .research_records import EpisodeRecord, RunInput, TraceMeasures

REQUIRED = {"protocol.json", "result.json", "scene.xml", "states.jsonl", "decisions.jsonl"}


class EvidenceError(ValueError):
    def __init__(self, code: str, status: str = "INVALID"):
        super().__init__(code)
        self.code, self.status = code, status


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_):
    raise EvidenceError("nonfinite_json")


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_pairs, parse_constant=_constant)


def _rows(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
            if not isinstance(row, dict):
                raise EvidenceError("invalid_log_row")
            yield row


def _hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest(root):
    manifest_path = root / "manifest.json"
    if not manifest_path.resolve().is_relative_to(root):
        raise EvidenceError("unsafe_manifest_path")
    if not manifest_path.is_file():
        raise EvidenceError("missing_manifest", "INCOMPLETE")
    entries = read_json(manifest_path)["artifacts"]
    hashes = {}
    for entry in entries:
        name, expected = entry["path"], entry["sha256"]
        relative = Path(name)
        if (
            not name
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != name
            or name == "manifest.json"
            or name in hashes
            or not (root / name).resolve().is_relative_to(root)
        ):
            raise EvidenceError("unsafe_or_duplicate_artifact_path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise EvidenceError("invalid_artifact_digest")
        path = root / name
        if not path.is_file():
            raise EvidenceError("missing_artifact", "INCOMPLETE")
        if _hash_file(path) != expected:
            raise EvidenceError("artifact_hash_mismatch")
        hashes[name] = expected
    if not REQUIRED <= hashes.keys():
        raise EvidenceError("missing_required_artifact", "INCOMPLETE")
    return hashes


def _number(value, *, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("invalid_numeric_measure")
    if nonnegative and value < 0:
        raise EvidenceError("negative_numeric_measure")
    return float(value)


def _count(value):
    if type(value) is not int or value < 0:
        raise EvidenceError("invalid_count")
    return value


def _trace(root, hashes, contract):
    first_time = last_time = initial = last_distance = None
    minimum, minimum_height, max_tilt, max_dwell = math.inf, math.inf, 0.0, 0.0
    previous_xy, length, samples = None, 0.0, 0
    goal = contract["goal"]["target_xy_m"]
    for row in _rows(root / "states.jsonl"):
        t = _number(row["time_s"], nonnegative=True)
        if last_time is not None and t <= last_time:
            raise EvidenceError("nonmonotonic_state_time")
        q = [_number(v) for v in row["qpos"]]
        if len(q) < 7:
            raise EvidenceError("short_robot_state")
        for key in ("qvel", "ctrl"):
            for value in row[key]:
                _number(value)
        distance = math.dist(q[:2], goal)
        reported = _number(row["goal_distance_m"], nonnegative=True)
        if not math.isclose(distance, reported, rel_tol=1e-6, abs_tol=1e-6):
            raise EvidenceError("goal_distance_mismatch")
        if first_time is None:
            first_time, initial = t, distance
        if previous_xy is not None:
            length += math.dist(q[:2], previous_xy)
        previous_xy, last_time, last_distance = q[:2], t, distance
        minimum, minimum_height = min(minimum, distance), min(minimum_height, q[2])
        norm = sum(v * v for v in q[3:7])
        if norm <= 0 or not math.isfinite(norm):
            raise EvidenceError("invalid_base_quaternion")
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * (q[4] ** 2 + q[5] ** 2) / norm))))
        max_tilt = max(max_tilt, tilt)
        max_dwell = max(max_dwell, _number(row["goal_dwell_s"], nonnegative=True))
        samples += 1
    if not samples:
        raise EvidenceError("empty_state_trace")
    actions, models, usage = Counter(), set(), {}
    for row in _rows(root / "decisions.jsonl"):
        if "action" not in row:
            continue
        if row.get("execution") == "accepted":
            actions[row["action"]["action"]] += 1
        meta = row.get("provider", {})
        if meta.get("model"):
            models.add(meta["model"])
        tokens = meta.get("usage")
        if tokens is not None and {"input_tokens", "output_tokens"} <= tokens.keys():
            call_id = row["observation_version"]
            if call_id in usage:
                raise EvidenceError("duplicate_call_usage")
            usage[call_id] = (_count(tokens["input_tokens"]), _count(tokens["output_tokens"]))
    events = None
    if "events.jsonl" in hashes:
        events = dict(Counter(row["event"] for row in _rows(root / "events.jsonl")))
    measures = TraceMeasures(
        state_samples=samples,
        first_sample_s=first_time,
        last_sample_s=last_time,
        initial_goal_distance_m=initial,
        minimum_goal_distance_m=minimum,
        last_sample_goal_distance_m=last_distance,
        sampled_progress_m=initial - last_distance,
        sampled_path_length_m=length,
        maximum_recorded_goal_dwell_s=max_dwell,
        minimum_base_height_m=minimum_height,
        maximum_base_tilt_deg=max_tilt,
        action_counts=dict(actions),
        event_counts=events,
    )
    return measures, sorted(models), list(usage.values())


def read_goal_run(source: RunInput) -> EpisodeRecord:
    """All expected evidence failures are recorded, not silently dropped or relabeled FAIL."""
    root = Path(source.path).resolve()
    source = source.model_copy(update={"path": str(root)})
    base = {"source": source}
    try:
        hashes = _manifest(root)
        base.update(
            artifact_hashes=hashes,
            # Portable content identity: copies cannot inflate the denominator.
            evidence_id=digest({name: hashes[name] for name in sorted(REQUIRED)}),
        )
        protocol, result = read_json(root / "protocol.json"), read_json(root / "result.json")
        if protocol.get("evaluation_profile") != "goal_outcome_v1":
            raise EvidenceError("legacy_or_unsupported_profile", "UNSUPPORTED")
        if protocol.get("schema_version") != "robot-goal-agent-v5":
            raise EvidenceError("unsupported_runner_version", "UNSUPPORTED")
        if not 1 <= _count(protocol["max_calls"]) <= 20:
            raise EvidenceError("invalid_episode_budget")
        if protocol["max_simulation_s"] is not None:
            _number(protocol["max_simulation_s"], nonnegative=True)
        contract = protocol["task_contract"]
        expected_contract = task_contract(
            [7.0, 0.0], protocol["max_calls"], protocol["max_simulation_s"]
        )
        if contract != expected_contract or protocol["task_contract_sha256"] != digest(contract):
            raise EvidenceError("task_contract_mismatch")
        for field in ("source_hashes", "robot_resources"):
            values = protocol[field]
            if (
                not isinstance(values, dict)
                or not values
                or not all(
                    isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in values.values()
                )
            ):
                raise EvidenceError("missing_or_invalid_robot_provenance")
        condition = {
            k: v for k, v in protocol.items() if k not in {"scene_revision", "scene_config"}
        }
        if (
            result["robot_condition_sha256"] != digest(condition)
            or result["scene_revision"] != protocol["scene_revision"]
        ):
            raise EvidenceError("result_condition_mismatch")
        valid = result["execution_valid"]
        if type(valid) is not bool or result["valid_execution"] is not valid:
            raise EvidenceError("invalid_execution_flags")
        goal_flag = result["goal_reached"]
        if not isinstance(result["reason"], str) or not result["reason"]:
            raise EvidenceError("invalid_termination_reason")
        if goal_flag is not None and type(goal_flag) is not bool:
            raise EvidenceError("invalid_goal_flag")
        evaluator = GoalEvaluator(contract)
        evaluator.goal_reached = goal_flag is True
        expected_result = evaluator.result(result["reason"], valid)
        if any(result.get(key) != value for key, value in expected_result.items()):
            raise EvidenceError("inconsistent_goal_outcome")
        if type(result["success"]) is not bool:
            raise EvidenceError("invalid_success_flag")
        if protocol["policy_origin"] not in {"openai_api", "mock"}:
            raise EvidenceError("invalid_policy_origin")
        if result["policy_origin"] != protocol["policy_origin"]:
            raise EvidenceError("policy_origin_mismatch")
        base.update(
            policy_origin=protocol["policy_origin"],
            termination_reason=result["reason"],
            simulation_s=_number(result["duration_s"], nonnegative=True),
            robot_api_calls=_count(result["api_calls_attempted"]),
            scene_id=digest({"revision": protocol["scene_revision"], "xml": hashes["scene.xml"]}),
        )
        policy_calls = _count(result["calls_attempted"]) if "calls_attempted" in result else None
        if base["robot_api_calls"] > protocol["max_calls"] or (
            policy_calls is not None and policy_calls > protocol["max_calls"]
        ):
            raise EvidenceError("episode_call_budget_exceeded")
        if policy_calls is not None and base["robot_api_calls"] > policy_calls:
            raise EvidenceError("inconsistent_policy_call_counts")
        if result["task_outcome"] == "INCONCLUSIVE":
            raise EvidenceError("inconclusive_execution", "INCONCLUSIVE")
        measures, models, usage = _trace(root, hashes, contract)
        if base["simulation_s"] < measures.last_sample_s:
            raise EvidenceError("duration_before_last_state")
        base.update(
            measures=measures,
            returned_models=models,
            condition_id=digest({"robot_condition": digest(condition), "returned_models": models}),
            calls_with_token_usage=len(usage),
            observed_input_tokens=sum(x[0] for x in usage) if usage else None,
            observed_output_tokens=sum(x[1] for x in usage) if usage else None,
            warnings=[
                "Goal outcome comes from the full-rate evaluator, not a sampled-state replay",
                "No failure-family detector is enabled; behavior events are not failure labels",
                "Identical core evidence is deduplicated; old runs have no execution UUID",
                "Token totals cover decision records only; pending/failed calls may be missing",
            ],
        )
        if protocol["policy_origin"] == "openai_api" and not models:
            base["warnings"].append("Returned model identity is unavailable")
        return EpisodeRecord(**base, status="VALID", task_outcome=result["task_outcome"])
    except EvidenceError as exc:
        status, reason = exc.status, exc.code
    except OSError:
        status, reason = "INCOMPLETE", "unreadable_evidence"
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError):
        status, reason = "INVALID", "malformed_evidence"
    # Remove partially extracted data if it cannot meet the strict record contract.
    safe = {
        key: base[key]
        for key in (
            "source",
            "evidence_id",
            "artifact_hashes",
            "simulation_s",
            "robot_api_calls",
            "scene_id",
            "policy_origin",
            "termination_reason",
        )
        if key in base
    }
    return EpisodeRecord(**safe, status=status, exclusion_reason=reason)
