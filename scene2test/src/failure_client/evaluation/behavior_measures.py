"""P1 passive, time-resolved evidence. Never changes a goal verdict or assigns a cause."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .goal_run_reader import EvidenceError, _manifest, _number, _rows, read_json
from .research_records import EpisodeRecord, StrictRecord


class EvidenceRef(StrictRecord):
    artifact: str
    sha256: str
    first_line: int | None = Field(default=None, ge=1)
    last_line: int | None = Field(default=None, ge=1)
    field: str | None = None

    @model_validator(mode="after")
    def ordered_lines(self):
        if self.first_line is not None and (
            self.last_line is None or self.last_line < self.first_line
        ):
            raise ValueError("invalid evidence line range")
        return self


class BehaviorInterval(StrictRecord):
    kind: Literal["phase", "contact", "fall", "recovery", "skill_event", "action_window"]
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, ge=0)
    timing: Literal["sampled", "event", "observation_window", "unknown"]
    phase: str | None = None
    censored: bool = False
    details: dict[str, float | int | bool | str | list[float] | None] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_time(self):
        if self.start_s is not None and self.end_s is not None and self.end_s < self.start_s:
            raise ValueError("reversed interval")
        return self


class BehaviorEvidence(StrictRecord):
    schema_version: Literal["behavior-evidence-v1"] = "behavior-evidence-v1"
    evidence_id: str | None
    task_outcome: str
    status: Literal["AVAILABLE", "PARTIAL", "EXCLUDED"]
    components: dict[str, str] = Field(default_factory=dict)
    intervals: list[BehaviorInterval] = Field(default_factory=list)
    object_motion: dict = Field(default_factory=dict)
    max_state_sample_gap_s: float | None = None
    warnings: list[str] = Field(default_factory=list)


def verify_episode_files(record: EpisodeRecord) -> Path:
    """Reject stale input between P0 import and P1 analysis/export, rather than weakening P0."""
    root = Path(record.source.path).resolve()
    if _manifest(root) != record.artifact_hashes:
        raise EvidenceError("source_changed_since_import")
    return root


def _ref(record, name, first=None, last=None, field=None):
    return EvidenceRef(
        artifact=name,
        sha256=record.artifact_hashes[name],
        first_line=first,
        last_line=first if first is not None and last is None else last,
        field=field,
    )


def _time(value, duration):
    value = _number(value, nonnegative=True)
    if duration is not None and value > duration + 1e-6:
        raise EvidenceError("timestamp_after_episode")
    return value


def _box_address(root, record):
    """Only the audited appended clear_box layout is supported; never guess qpos[-7:]."""
    if "robot_audit.json" not in record.artifact_hashes:
        return None
    audit = read_json(root / "robot_audit.json")
    base, combined = audit["baseline_nq_nv"], audit["combined_nq_nv"]
    if (
        audit.get("schema_version") != "clear-path-robot-audit-v1"
        or audit.get("robot_joint_identity_preserved") is not True
        or audit.get("gait_observation_equal") is not True
        or len(base) != 2
        or len(combined) != 2
        or any(type(v) is not int or v < 0 for v in [*base, *combined])
        or base[0] < 7
        or base[1] < 6
        or combined != [base[0] + 7, base[1] + 6]
    ):
        raise EvidenceError("unsupported_box_state_mapping")
    xml = ET.parse(root / "scene.xml").getroot()
    body = xml.find("./worldbody/body[@name='clear_box']")
    geom = None if body is None else body.find("geom[@name='clear_box_geom']")
    if (
        body is None
        or body.find("freejoint[@name='clear_box_free']") is None
        or geom is None
        or [_number(float(v)) for v in geom.get("pos", "0 0 0").split()] != [0, 0, 0]
        or len(body.findall("joint")) != 0
        or len(body.findall("freejoint")) != 1
    ):
        raise EvidenceError("unsupported_box_geometry")
    return base[0], combined[0]


def _state_intervals(root, record, box_address):
    intervals, current, previous_time, max_gap = [], None, None, 0.0
    box_first = box_last = None
    box_path = 0.0
    box_error = "no_validated_box_state_mapping"
    count = 0

    def finish(segment):
        intervals.append(
            BehaviorInterval(
                kind="phase",
                start_s=segment["start"],
                end_s=segment["end"],
                timing="sampled",
                phase=segment["phase"],
                details={
                    "state_samples": segment["n"],
                    "path_length_m": segment["path"],
                    "goal_progress_m": segment["initial_distance"] - segment["distance"],
                    "initial_goal_distance_m": segment["initial_distance"],
                    "last_goal_distance_m": segment["distance"],
                },
                evidence=[_ref(record, "states.jsonl", segment["first"], segment["last"])],
            )
        )

    for line, row in enumerate(_rows(root / "states.jsonl"), 1):
        t = _time(row["time_s"], record.simulation_s)
        if previous_time is not None:
            if t <= previous_time:
                raise EvidenceError("nonmonotonic_state_time")
            max_gap = max(max_gap, t - previous_time)
        previous_time = t
        phase = row.get("phase", "unknown")
        if not isinstance(phase, str):
            raise EvidenceError("invalid_phase")
        q = [_number(v) for v in row["qpos"]]
        distance = _number(row["goal_distance_m"], nonnegative=True)
        if current is None or phase != current["phase"]:
            if current:
                finish(current)
            current = {
                "phase": phase,
                "start": t,
                "first": line,
                "n": 0,
                "path": 0.0,
                "initial_distance": distance,
                "last_xy": q[:2],
            }
        current["path"] += math.dist(q[:2], current["last_xy"])
        current.update(end=t, last=line, n=current["n"] + 1, distance=distance, last_xy=q[:2])
        if box_address:
            adr, nq = box_address
            if len(q) != nq:
                box_address, box_first, box_last = None, None, None
                box_error = "box_state_length_mismatch"
                count += 1
                continue
            xyz = q[adr : adr + 3]
            if box_first is None:
                box_first = {"time_s": t, "xyz_m": xyz}
            if box_last:
                box_path += math.dist(xyz[:2], box_last["xyz_m"][:2])
            box_last = {"time_s": t, "xyz_m": xyz}
        count += 1
    if not current:
        raise EvidenceError("empty_state_trace")
    finish(current)
    motion = {"status": "UNSUPPORTED", "reason": box_error}
    if box_first is not None:
        motion = {
            "status": "AVAILABLE",
            "entity": "clear_box_geom",
            "basis": "audited_qpos_samples",
            "first_sample": box_first,
            "last_sample": box_last,
            "samples": count,
            "net_xy_displacement_m": math.dist(box_first["xyz_m"][:2], box_last["xyz_m"][:2]),
            "sampled_xy_path_length_m": box_path,
            "evidence": [
                _ref(record, "robot_audit.json", field="baseline_nq_nv").model_dump(),
                _ref(record, "scene.xml", field="clear_box_free").model_dump(),
                _ref(record, "states.jsonl", 1, count, field="qpos").model_dump(),
            ],
            "limits": "Sampled motion is not evidence of an intentional/successful push",
        }
        if not all(
            math.isfinite(motion[k]) for k in ("net_xy_displacement_m", "sampled_xy_path_length_m")
        ):
            motion = {"status": "INVALID", "reason": "nonfinite_derived_box_motion"}
    return intervals, motion, max_gap


def _event_intervals(root, record):
    active, result, last_time, warnings = {}, [], -1.0, []
    for line, row in enumerate(_rows(root / "events.jsonl"), 1):
        t = _time(row["time_s"], record.simulation_s)
        if t < last_time:
            raise EvidenceError("nonmonotonic_event_time")
        last_time = t
        event, phase = row["event"], row.get("phase")
        if event in {"contact_start", "contact_end", "fall_start", "fall_end"}:
            kind, endpoint = event.split("_")
            start_phase = row.get("start_phase", phase)
            key = (
                (kind, row.get("robot_geom"), row.get("world_geom"), start_phase)
                if (kind == "contact")
                else ("fall",)
            )
            if endpoint == "start":
                if key in active:
                    raise EvidenceError("duplicate_active_event")
                active[key] = (line, row)
                continue
            prior = active.pop(key, None)
            start = _time(row["start_s"], record.simulation_s)
            if prior and not math.isclose(start, prior[1]["time_s"], abs_tol=1e-8):
                raise EvidenceError("event_endpoint_mismatch")
            if not prior:
                warnings.append("event_end_without_start")
            details = {
                k: row[k] for k in ("robot_body", "world_geom_name", "legacy_allowed") if k in row
            }
            for field in ("peak_normal_force_n", "normal_impulse_ns", "sampled_duration_s"):
                if field in row:
                    details[field] = _number(row[field], nonnegative=True)
            if kind == "contact":
                details["support_contact"] = details.get(
                    "world_geom_name"
                ) == "clear_floor" and str(details.get("robot_body", "")).endswith(
                    "ankle_roll_link"
                )
            truncated = row["truncated"]
            if type(truncated) is not bool:
                raise EvidenceError("invalid_truncation_flag")
            result.append(
                BehaviorInterval(
                    kind=kind,
                    start_s=start,
                    end_s=t,
                    timing="event",
                    phase=start_phase,
                    censored=truncated or prior is None,
                    details=details,
                    evidence=[
                        _ref(record, "events.jsonl", n)
                        for n in ([prior[0], line] if prior else [line])
                    ],
                )
            )
        elif event in {"upright_recovered", "skill_failure", "skill_interrupted"}:
            result.append(
                BehaviorInterval(
                    kind="recovery" if event == "upright_recovered" else "skill_event",
                    start_s=t,
                    end_s=t,
                    timing="event",
                    phase=phase,
                    details={k: row[k] for k in ("event", "skill", "reason") if k in row},
                    evidence=[_ref(record, "events.jsonl", line)],
                )
            )
        else:
            warnings.append("unknown_event_type")
    for line, row in active.values():
        warnings.append("unclosed_event")
        result.append(
            BehaviorInterval(
                kind=row["event"].split("_")[0],
                start_s=row["time_s"],
                end_s=None,
                timing="event",
                phase=row.get("phase"),
                censored=True,
                details={"endpoint_status": "missing_end"},
                evidence=[_ref(record, "events.jsonl", line)],
            )
        )
    return result, sorted(set(warnings))


def _action_intervals(root, record):
    choices, finishes, result = {}, {}, []
    for line, row in enumerate(_rows(root / "decisions.jsonl"), 1):
        if "action" not in row and row.get("event") != "tool_result":
            continue
        cid = row["observation_version"]
        if type(cid) is not int or not 0 <= cid < 20:
            raise EvidenceError("invalid_observation_version")
        target = choices if "action" in row else finishes
        if cid in target:
            raise EvidenceError("duplicate_action_record")
        target[cid] = (line, row)
    if not finishes.keys() <= choices.keys():
        raise EvidenceError("tool_result_without_action")
    for cid, (line, row) in choices.items():
        refs = [_ref(record, "decisions.jsonl", line)]
        observation = f"observation_{cid:03}.json"
        start = end = None
        if observation in record.artifact_hashes:
            obs = read_json(root / observation)
            if obs["state_version"] != cid:
                raise EvidenceError("observation_id_mismatch")
            start = _time(obs["simulation_time_s"], record.simulation_s)
            refs.append(_ref(record, observation, field="simulation_time_s"))
        action = row["action"]
        details = {
            "observation_version": cid,
            "action": action["action"],
            "execution": row["execution"],
            "includes_inference_wait": True,
            "execution_start_s": None,
        }
        for key in ("object_id", "target_xy_m", "duration_s", "vx_mps", "vy_mps", "yaw_rate_rps"):
            if key in action:
                details[key] = action[key]
        if "latency_s" in row:
            details["inference_wall_s"] = _number(row["latency_s"], nonnegative=True)
        if cid in finishes:
            n, finish = finishes[cid]
            feedback = finish["result"]
            end = _time(feedback["simulation_time_s"], record.simulation_s)
            refs.append(_ref(record, "decisions.jsonl", n, field="result"))
            for field in ("status", "reason", "success", "terminal_reason"):
                if field in feedback:
                    details["tool_" + field] = feedback[field]
            # Optional full-rate action-end readings. Missing old measurements
            # remain absent, never zero; they do not change goal labels/taxonomy.
            if "goal_progress" in feedback:
                progress = feedback["goal_progress"]
                for field in ("distance_m", "current_dwell_s", "remaining_dwell_s"):
                    value = progress[field]
                    details["goal_" + field] = (
                        None if value is None else _number(value, nonnegative=True)
                    )
            if "motion" in feedback:
                motion = feedback["motion"]
                if motion.get("version") != "action-motion-v1":
                    raise EvidenceError("unsupported_motion_feedback")
                motion_start = _time(motion["start_simulation_s"], record.simulation_s)
                motion_end = _time(motion["end_simulation_s"], record.simulation_s)
                elapsed = _number(motion["elapsed_s"], nonnegative=True)
                if (
                    motion_end != end
                    or motion_start > motion_end
                    or (start is not None and motion_start < start)
                    or abs(motion_end - motion_start - elapsed) > 1e-6
                ):
                    raise EvidenceError("invalid_motion_window")
                details["execution_start_s"] = motion_start
                details["motion_elapsed_s"] = elapsed
                for field, nonnegative in (
                    ("net_translation_m", True),
                    ("goal_distance_reduction_m", False),
                ):
                    details["motion_" + field] = _number(motion[field], nonnegative=nonnegative)
                stationary = motion["commanded_stationary"]
                expected = (
                    all(action.get(k) == 0 for k in ("vx_mps", "vy_mps", "yaw_rate_rps"))
                    if action["action"] == "move"
                    else None
                )
                if stationary is not expected:
                    raise EvidenceError("motion_command_mismatch")
                details["motion_commanded_stationary"] = stationary
                fraction = motion["yaw_limit_fraction"]
                if fraction is not None and not 0 <= _number(fraction) <= 1:
                    raise EvidenceError("invalid_yaw_limit_fraction")
                details["motion_yaw_limit_fraction"] = fraction
                blocked = motion["blocked_connector_samples"]
                if type(blocked) is not int or blocked < 0:
                    raise EvidenceError("invalid_blocked_connector_count")
                details["motion_blocked_connector_samples"] = blocked
            if "navigation_recovery" in feedback:
                recovery = feedback["navigation_recovery"]
                if (
                    recovery.get("version") != "clearance-recovery-v3"
                    or action["action"] != "navigate_to"
                ):
                    raise EvidenceError("unsupported_navigation_recovery")
                if _time(recovery["ended_at_simulation_s"], record.simulation_s) != end:
                    raise EvidenceError("invalid_navigation_recovery_time")
                for field in ("recovery_count", "replan_count"):
                    value = recovery[field]
                    if type(value) is not int or not 0 <= value <= 2:
                        raise EvidenceError("invalid_navigation_recovery_count")
                    details["navigation_" + field] = value
                status = recovery["status"]
                if not isinstance(status, str) or not 0 < len(status) <= 80:
                    raise EvidenceError("invalid_navigation_recovery_status")
                details["navigation_recovery_status"] = status
                events = recovery["events"]
                if not isinstance(events, list) or len(events) > 12:
                    raise EvidenceError("invalid_navigation_recovery_events")
                previous = (
                    details["execution_start_s"]
                    if details["execution_start_s"] is not None
                    else start
                )
                summary = []
                names = {
                    "blocked_connector",
                    "recovery_started",
                    "recovery_completed",
                    "replan",
                    "tool_return",
                }
                for event in events:
                    time_s = _time(event["simulation_time_s"], record.simulation_s)
                    if (
                        (previous is not None and time_s < previous)
                        or time_s > end
                        or event["event"] not in names
                    ):
                        raise EvidenceError("invalid_navigation_recovery_event")
                    previous = time_s
                    label = event.get("reason", event.get("plan_status"))
                    if label is not None and (not isinstance(label, str) or len(label) > 80):
                        raise EvidenceError("invalid_navigation_recovery_event_label")
                    summary.append(
                        f"{time_s:.6f}s {event['event']}" + (f" ({label})" if label else "")
                    )
                if (
                    sum(e["event"] == "recovery_started" for e in events)
                    != recovery["recovery_count"]
                    or sum(e["event"] == "replan" for e in events) != recovery["replan_count"]
                ):
                    raise EvidenceError("navigation_recovery_event_count_mismatch")
                details["navigation_recovery_timeline"] = "; ".join(summary)
        skill = f"skill_{cid:03}.json"
        if skill in record.artifact_hashes:
            saved = read_json(root / skill)
            if cid not in finishes or saved != finishes[cid][1]["result"]:
                raise EvidenceError("skill_result_mismatch")
            refs.append(_ref(record, skill))
        result.append(
            BehaviorInterval(
                kind="action_window",
                start_s=start,
                end_s=end,
                timing="observation_window" if start is not None else "unknown",
                censored=start is None or end is None,
                details=details,
                evidence=refs,
            )
        )
    return result


def analyze_behavior(record: EpisodeRecord) -> BehaviorEvidence:
    """Optional malformed telemetry makes analysis partial, not the robot a failure."""
    report = BehaviorEvidence(
        evidence_id=record.evidence_id,
        task_outcome=record.task_outcome,
        status="EXCLUDED",
    )
    if record.status != "VALID":
        report.warnings = [record.exclusion_reason or record.status]
        return report
    root = verify_episode_files(record)
    report.status = "AVAILABLE"
    address = None
    try:
        address = _box_address(root, record)
    except (ValueError, KeyError, TypeError, ET.ParseError, OSError) as exc:
        report.warnings.append("box_mapping_invalid:" + type(exc).__name__)
    for component in ("states", "events", "actions"):
        if component == "events" and "events.jsonl" not in record.artifact_hashes:
            report.components[component] = "UNAVAILABLE"
            continue
        try:
            if component == "states":
                intervals, motion, gap = _state_intervals(root, record, address)
                report.object_motion, report.max_state_sample_gap_s = motion, gap
            elif component == "events":
                intervals, warnings = _event_intervals(root, record)
                report.warnings.extend(warnings)
            else:
                intervals = _action_intervals(root, record)
            report.intervals.extend(intervals)
            report.components[component] = "AVAILABLE"
        except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            report.components[component] = "INVALID"
            report.warnings.append(
                component
                + ":"
                + (exc.code if isinstance(exc, EvidenceError) else type(exc).__name__)
            )
    report.components["object_motion"] = report.object_motion.get("status", "UNAVAILABLE")
    if any(i.kind == "action_window" and i.start_s is None for i in report.intervals):
        report.warnings.append("action_observation_time_missing")
    if report.warnings or any(v != "AVAILABLE" for v in report.components.values()):
        report.status = "PARTIAL"
    report.intervals.sort(key=lambda i: (i.start_s is None, i.start_s or 0, i.kind))
    return report


def interval_summary(report: BehaviorEvidence):
    """Counts are observations, NOT failure types, and unknown telemetry is not zero."""
    counts = Counter(i.kind for i in report.intervals)
    return {
        "phase_intervals": counts["phase"]
        if report.components.get("states") == "AVAILABLE"
        else None,
        "contact_intervals": counts["contact"]
        if report.components.get("events") == "AVAILABLE"
        else None,
        "fall_intervals": counts["fall"]
        if report.components.get("events") == "AVAILABLE"
        else None,
        "recovery_events": counts["recovery"]
        if report.components.get("events") == "AVAILABLE"
        else None,
        "action_windows": counts["action_window"]
        if report.components.get("actions") == "AVAILABLE"
        else None,
    }
