"""Opt-in, conservative temporal associations; NEVER changes a goal verdict.

No LLM labels or static no_path impossibility claims. Rules describe recorded
terminal behavior, not counterfactually established causes. Ambiguity stays UNKNOWN.
"""

import math
import xml.etree.ElementTree as ET

import numpy as np

from .behavior_measures import _box_address, analyze_behavior, verify_episode_files
from .goal_run_reader import _rows, read_json
from .research_records import FAMILIES, Attribution, EpisodeRecord

PROFILE = "goal-behavior-v1"
RULES = {
    family: PROFILE + "/" + family
    for family in ("collision", "obstacle_interference", "goal_occupied")
}
THRESHOLDS = {
    "terminal_window_s": 5.0,
    "max_state_gap_s": 0.25,
    "max_goal_distance_range_m": 0.15,
    "max_base_excursion_m": 0.35,
    "contact_duration_s": 0.2,
    "contact_force_n": 10.0,
    "recent_contact_s": 2.0,
    "blocked_tool_window_s": 10.0,
    "blocked_tool_count": 2,
    "near_obstacle_m": 0.55,
}


def _rotation(quat):
    q = np.asarray(quat, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or np.linalg.norm(q) < 1e-12:
        raise ValueError("invalid_geometry_quaternion")
    w, x, y, z = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _objects(xml, qpos, box_address):
    objects = []
    for geom in xml.findall("worldbody/geom"):
        if geom.get("name") == "clear_floor":
            continue
        xyz = np.array([float(v) for v in geom.get("pos").split()])
        half = np.array([float(v) for v in geom.get("size").split()])
        rot = _rotation([float(v) for v in geom.get("quat", "1 0 0 0").split()])
        objects.append((geom.get("name"), xyz, half, rot))
    if box_address is None or len(qpos) != box_address[1]:
        raise ValueError("audited_box_state_required")
    adr = box_address[0]
    geom = xml.find("worldbody/body[@name='clear_box']/geom[@name='clear_box_geom']")
    objects.append(
        (
            "clear_box_geom",
            np.asarray(qpos[adr : adr + 3]),
            np.array([float(v) for v in geom.get("size").split()]),
            _rotation(qpos[adr + 3 : adr + 7]),
        )
    )
    return objects


def _projected_point_distance(point, obj):
    _, xyz, half, rotation = obj
    # For upright boxes use the exact oriented XY rectangle. Tilted boxes cannot
    # establish goal occupancy; proximity can still use their conservative AABB.
    if abs(rotation[2, 2]) < 1 - 1e-6:
        extent = (np.abs(rotation) @ half)[:2]
        delta = np.maximum(np.abs(np.asarray(point) - xyz[:2]) - extent, 0)
        return float(np.linalg.norm(delta)), None
    local = rotation[:2, :2].T @ (np.asarray(point) - xyz[:2])
    return float(np.linalg.norm(np.maximum(np.abs(local) - half[:2], 0))), half[:2] - np.abs(local)


def measure_taxonomy(record, behavior=None):
    report = {
        "schema_version": PROFILE,
        "evidence_id": record.evidence_id,
        "task_outcome": record.task_outcome,
        "primary_family": None,
        "causal_status": "UNCONFIRMED",
        "thresholds": dict(THRESHOLDS),
        "families": {
            f: {"status": "UNKNOWN" if f in RULES else "UNSUPPORTED", "rule_version": RULES.get(f)}
            for f in FAMILIES
        },
        "measurements": {},
        "evidence": [],
        "warnings": [],
        "limits": [
            "Temporal association, not a demonstrated cause or impossibility",
            "Ground-truth scene geometry; no perception/human/reachability detector",
            "State windows include inference; no invented precise action start",
        ],
    }
    if record.status != "VALID":
        report["warnings"].append("excluded_episode")
        return report
    root = verify_episode_files(record)
    behavior = behavior or analyze_behavior(record)

    def ref(name, first=None, last=None):
        row = {"artifact": name, "sha256": record.artifact_hashes[name]}
        if first is not None:
            row.update(first_line=first, last_line=last if last is not None else first)
        if row not in report["evidence"]:
            report["evidence"].append(row)

    ref("result.json")
    states = list(_rows(root / "states.jsonl"))
    end = states[-1]["time_s"]
    start = end - THRESHOLDS["terminal_window_s"]
    window = [(n, s) for n, s in enumerate(states, 1) if s["time_s"] >= start - 1e-8]
    complete = (
        len(window) >= 2
        and window[0][1]["time_s"] <= start + 0.25
        and end >= 5
        and record.simulation_s - end <= 0.25
        and all(b[1]["time_s"] - a[1]["time_s"] <= 0.25 + 1e-8 for a, b in zip(window, window[1:]))
    )
    goal = read_json(root / "protocol.json")["task_contract"]["goal"]
    distances = [s["goal_distance_m"] for _, s in window]
    excursion = max(math.dist(s["qpos"][:2], window[0][1]["qpos"][:2]) for _, s in window)
    stalled = (
        complete
        and min(distances) > goal["radius_m"]
        and max(distances) - min(distances) <= 0.15
        and excursion <= 0.35
    )
    report["measurements"]["terminal_progress"] = {
        "status": "AVAILABLE" if complete else "UNKNOWN",
        "start_s": start,
        "end_s": end,
        "stalled": stalled if complete else None,
        "goal_distance_range_m": max(distances) - min(distances),
        "base_excursion_m": excursion,
        "remaining_goal_distance_m": distances[-1],
    }
    ref("states.jsonl", window[0][0], window[-1][0])
    contacts = [
        i
        for i in behavior.intervals
        if i.kind == "contact" and not i.details.get("support_contact")
    ]
    qualifying_contacts = [
        i
        for i in contacts
        if (
            not i.censored
            and i.phase in {"navigate_to", "move"}
            and i.details.get("world_geom_name") not in {None, "clear_floor", "clear_box_geom"}
            and i.end_s >= end - 2
            and i.end_s - i.start_s >= 0.2
            and i.details.get("peak_normal_force_n", 0) >= 10
        )
    ]
    report["measurements"]["non_support_contacts"] = {
        "status": behavior.components.get("events", "UNAVAILABLE"),
        "count": len(contacts) if behavior.components.get("events") == "AVAILABLE" else None,
        "terminal_navigation_contacts": [i.model_dump() for i in qualifying_contacts],
    }
    actions = [i for i in behavior.intervals if i.kind == "action_window"]
    blocked = [
        i
        for i in actions
        if i.end_s is not None
        and end - 10 <= i.end_s <= end + 0.25
        and i.details.get("execution") == "accepted"
        and i.details.get("action") in {"plan_path", "navigate_to"}
        and i.details.get("tool_status") in {"no_path", "blocked_endpoint"}
    ]
    report["measurements"]["blocked_tools"] = [i.model_dump() for i in blocked]
    try:
        from failure_client.archive.regression_cases import _scene_parameters

        protocol = read_json(root / "protocol.json")
        if _scene_parameters(root, protocol)[0] is None:
            raise ValueError("scene_geometry_not_verified")
        xml = ET.parse(root / "scene.xml").getroot()
        address = _box_address(root, record)
        frames = [_objects(xml, s["qpos"], address) for _, s in window]
        nearest = {
            obj[0]: _projected_point_distance(window[-1][1]["qpos"][:2], obj)[0]
            for obj in frames[-1]
        }
        known_contacts = [i for i in qualifying_contacts if i.details["world_geom_name"] in nearest]
        if behavior.components.get("events") == "AVAILABLE" and complete:
            if len(known_contacts) != len(qualifying_contacts):
                report["warnings"].append("unrecognized_contact_geometry")
            elif (
                not known_contacts
                and stalled
                and any(i.censored and (i.end_s is None or i.end_s >= start) for i in contacts)
            ):
                report["warnings"].append("censored_terminal_contact")
            else:
                report["families"]["collision"]["status"] = (
                    "DETECTED" if stalled and known_contacts else "NOT_DETECTED"
                )
            ref("events.jsonl")
        covering = None
        for objects in frames:
            # Full goal disk inside one upright projected obstacle, not mere touching.
            now = {
                o[0]
                for o in objects
                if (
                    (m := _projected_point_distance(goal["target_xy_m"], o)[1]) is not None
                    and min(m) >= goal["radius_m"]
                    and o[1][2] - o[2][2] <= 0.1
                )
            }
            covering = now if covering is None else covering & now
        report["measurements"]["geometry"] = {
            "status": "AVAILABLE",
            "terminal_base_distance_to_obstacles_m": nearest,
            "goal_disk_covered_through_window_by": sorted(covering),
            "interpretation": "Projected occupancy; does not prove jumping/manipulation impossible",
        }
        ref("scene.xml")
        ref("protocol.json")
        ref("robot_audit.json")
        if complete:
            tilted = any(abs(o[3][2, 2]) < 1 - 1e-6 for objects in frames for o in objects)
            report["families"]["goal_occupied"]["status"] = (
                "DETECTED"
                if covering and stalled
                else "UNKNOWN"
                if tilted and stalled
                else "NOT_DETECTED"
            )
            if behavior.components.get("actions") == "AVAILABLE":
                interference = stalled and len(blocked) >= 2 and min(nearest.values()) <= 0.55
                report["families"]["obstacle_interference"]["status"] = (
                    "DETECTED" if interference else "NOT_DETECTED"
                )
                ref("decisions.jsonl")
                for interval in blocked:
                    for e in interval.evidence:
                        ref(e.artifact, e.first_line, e.last_line)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ET.ParseError) as exc:
        report["measurements"]["geometry"] = {"status": "UNKNOWN", "reason": type(exc).__name__}
        report["warnings"].append("geometry_evidence_unavailable")
    detected = [f for f, row in report["families"].items() if row["status"] == "DETECTED"]
    if record.task_outcome == "PASS":
        for f in RULES:
            report["families"][f]["diagnostic_status"] = report["families"][f]["status"]
            report["families"][f]["status"] = "N/A"
    elif len(detected) == 1:
        report["primary_family"] = detected[0]
    elif len(detected) > 1:
        report["warnings"].append("ambiguous_multiple_families")
    if not complete:
        report["warnings"].append("terminal_state_window_incomplete")
    return report


def classify_record(record):
    report = measure_taxonomy(record)
    attribution = None
    if report["primary_family"] is not None:
        f = report["primary_family"]
        attribution = Attribution(
            primary_family=f,
            rule_version=RULES[f],
            evidence_refs=sorted({e["artifact"] for e in report["evidence"]}),
        )
    return EpisodeRecord.model_validate(
        {
            **record.model_dump(),
            "taxonomy": report,
            "attribution": attribution.model_dump() if attribution else None,
        }
    )
