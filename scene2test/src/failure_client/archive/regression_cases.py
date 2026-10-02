"""P1 failure memory: immutable evidence bundles and empirical, noncausal brackets.

No policy invocation, remote writes or automatic regression execution.
Robot assets remain explicitly hashed external dependencies, not silently copied.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shlex
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from clear_path.contracts import CorridorFixture
from clear_path.fixture import identity, world_xml
from clear_path.scene_space import axes_for_parameters
from failure_client.evaluation.behavior_measures import analyze_behavior, interval_summary
from failure_client.evaluation.goal_run_reader import _hash_file, _rows, read_json
from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.reporting.discovery_metrics import deduplicate_records
from robot_vlm.navigation_completion import profile_from_protocol
from robot_vlm.scene_config import validate_scene
from robot_vlm.task_outcome import digest

COPY_FILES = {
    "protocol.json",
    "result.json",
    "scene.xml",
    "states.jsonl",
    "decisions.jsonl",
    "events.jsonl",
    "robot_audit.json",
    "terminal_state.json",
    "scene_graph.json",
    "navigation_map.json",
}
COPY_PATTERN = re.compile(r"(?:observation|skill|tool)_\d{3}\.json|camera_\d{3}\.png")
SECRET_KEYS = {
    "api_key",
    "openai_api_key",
    "authorization",
    "password",
    "access_token",
    "refresh_token",
    "api_token",
    "token",
    "client_secret",
    "credentials",
    "secret",
    "api-key",
    "x-api-key",
}


def _scene_parameters(root, protocol):
    try:
        config = validate_scene(protocol["scene_config"])
        if identity(config) != protocol["scene_revision"]:
            raise ValueError("scene_revision_mismatch")
        xml = ET.parse(root / "scene.xml").getroot()
        expected = ET.fromstring(world_xml(config)).find("worldbody")
        actual = xml.find("worldbody")
        if actual is None or {g.get("name") for g in actual.findall("geom")} != {
            g.get("name") for g in expected.findall("geom")
        }:
            raise ValueError("unsupported_static_geometry")
        for node in expected:
            if node.tag not in {"geom", "body", "site"}:
                continue
            matches = actual.findall(f"{node.tag}[@name='{node.get('name')}']")
            if len(matches) != 1 or ET.canonicalize(
                ET.tostring(node, encoding="unicode"), strip_text=True
            ) != ET.canonicalize(ET.tostring(matches[0], encoding="unicode"), strip_text=True):
                raise ValueError("static_geometry_not_reproducible_from_config")
        boxes = xml.findall(".//geom[@name='clear_box_geom']")
        floors = xml.findall(".//geom[@name='clear_floor']")
        if len(boxes) != 1 or len(floors) != 1:
            raise ValueError("unsupported_scene_geometry")
        box, floor = boxes[0], floors[0]
        for node, field, expected in (
            (box, "mass", config.box_mass_kg),
            (box, "friction", config.box_friction),
            (floor, "friction", config.floor_friction),
        ):
            values = [float(x) for x in node.attrib[field].split()]
            if (
                not values
                or not all(math.isfinite(v) for v in values)
                or not math.isclose(values[0], expected, abs_tol=1e-9, rel_tol=1e-9)
            ):
                raise ValueError("scene_parameter_mismatch")
            node.set(field, "CONTROLLED " + " ".join(str(x) for x in values[1:]))
        if isinstance(config, CorridorFixture):
            # Verify first, normalize second: only generated scene-owned nodes are
            # replaced. Preserve every robot/compiler/physics difference in the hash.
            baseline = ET.fromstring(world_xml(type(config)())).find("worldbody")
            for node in baseline:
                if node.tag not in {"geom", "body", "site"}:
                    continue
                match = actual.find(f"{node.tag}[@name='{node.get('name')}']")
                index = list(actual).index(match)
                actual.remove(match)
                actual.insert(index, copy.deepcopy(node))
        # v1 normalizes physics values; v2/v3 also normalize audited scene-owned geometry.
        geometry = hashlib.sha256(
            ET.canonicalize(ET.tostring(xml, encoding="unicode")).encode()
        ).hexdigest()
        return config.model_dump(), geometry, None
    except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
        return None, None, "scene_parameters_unverified:" + type(exc).__name__


def _brackets(cases):
    buckets = defaultdict(lambda: defaultdict(list))
    for case in cases:
        if case["parameters"] is None:
            continue
        params = case["parameters"]
        for axis in axes_for_parameters(params):
            frozen = tuple((k, params[k]) for k in sorted(params) if k != axis)
            key = (case["condition_id"], case["geometry_id"], axis, frozen)
            buckets[key][params[axis]].append(case)
    result = []
    for (_, _, axis, _), points in buckets.items():
        ordered = sorted(points.items())
        for (low, left), (high, right) in zip(ordered, ordered[1:]):

            def endpoint(value, rows):
                passes = sum(c["pass_count"] for c in rows)
                failures = sum(c["fail_count"] for c in rows)
                return {
                    "value": value,
                    "case_ids": [c["case_id"] for c in rows],
                    "passes": passes,
                    "failures": failures,
                    "outcome": "MIXED" if passes and failures else "PASS" if passes else "FAIL",
                }

            a, b = endpoint(low, left), endpoint(high, right)
            if {a["outcome"], b["outcome"]} != {"PASS", "FAIL"}:
                continue
            result.append(
                {
                    "status": "observed_bracket",
                    "axis": axis,
                    "low": a,
                    "high": b,
                    "normalized_width": (high - low)
                    / (
                        axes_for_parameters(left[0]["parameters"])[axis][1]
                        - axes_for_parameters(left[0]["parameters"])[axis][0]
                    ),
                    "midpoint_probe": (low + high) / 2,
                    "limits": (
                        "Observed endpoints only; no monotonicity, causal or minimal-boundary proof"
                    ),
                }
            )
    return result


def build_failure_memory(records):
    records = [EpisodeRecord.model_validate(r.model_dump()) for r in records]
    records, duplicates = deduplicate_records(records)
    cases, episodes, excluded = {}, {}, []
    for record in records:
        if record.status != "VALID":
            excluded.append(
                {
                    "source": record.source.path,
                    "status": record.status,
                    "reason": record.exclusion_reason,
                }
            )
            continue
        analysis = analyze_behavior(record)  # re-verifies the source manifest
        root = Path(record.source.path)
        protocol = read_json(root / "protocol.json")
        params, geometry, warning = _scene_parameters(root, protocol)
        case_id = digest({"condition": record.condition_id, "scene": record.scene_id})
        case = cases.setdefault(
            case_id,
            {
                "case_id": case_id,
                "condition_id": record.condition_id,
                "scene_id": record.scene_id,
                "policy_origin": record.policy_origin,
                "task_contract": protocol["task_contract"],
                "parameters": params,
                "geometry_id": geometry,
                "pass_count": 0,
                "fail_count": 0,
                "episodes": [],
                "primary_family": None,
                "causal_status": "UNKNOWN",
                "warnings": [warning] if warning else [],
                "reproduction": {
                    "schema_version": "goal-agent-reproduction-v1",
                    "status": "external_dependencies_not_verified"
                    if params
                    else "unsupported_scene",
                    "source_hashes": protocol["source_hashes"],
                    "robot_resources": protocol["robot_resources"],
                    "model": protocol.get("model"),
                    "returned_models": record.returned_models,
                    "max_calls": protocol["max_calls"],
                    "max_simulation_s": protocol["max_simulation_s"],
                    "http_read_timeout_s": protocol.get("http_read_timeout_s"),
                    "push_enabled": protocol.get("push_enabled"),
                    "policy_origin": record.policy_origin,
                    "evaluation_profile": protocol["evaluation_profile"],
                    "navigation_completion": profile_from_protocol(protocol),
                    "limits": (
                        "No replay was executed; external model responses need not be deterministic"
                    ),
                },
            },
        )
        case["pass_count" if record.task_outcome == "PASS" else "fail_count"] += 1
        case["episodes"].append(record.evidence_id)
        episodes[record.evidence_id] = {
            "record": record.model_dump(),
            "behavior": analysis.model_dump(),
            "summary": interval_summary(analysis),
        }
    for case in cases.values():
        p, f = case["pass_count"], case["fail_count"]
        case["empirical_failure_rate"] = f / (p + f)
        case["role"] = (
            "mixed_outcomes" if p and f else "observed_failure" if f else "success_control"
        )
        case["confirmation_status"] = "observations_only"
        labels = {
            episodes[e]["record"]["taxonomy"]["primary_family"]
            for e in case["episodes"]
            if episodes[e]["record"].get("taxonomy", {}).get("primary_family")
        }
        case["operational_family_candidates"] = sorted(labels)
        # Mixed repeats or incomplete/ambiguous labels are not a stable case label.
        if (
            f
            and not p
            and len(labels) == 1
            and all(
                episodes[e]["record"].get("taxonomy", {}).get("primary_family") in labels
                for e in case["episodes"]
            )
        ):
            case["primary_family"] = next(iter(labels))
            case["causal_status"] = "UNCONFIRMED"
    cases = list(cases.values())
    memory = {
        "schema_version": "failure-memory-v1",
        "cases": cases,
        "episodes": episodes,
        "brackets": _brackets(cases),
        "excluded": excluded,
        "duplicates": duplicates,
        "limits": [
            "Events are evidence, not automatic failure-family or causal labels",
            "Success controls and mixed repeats are retained alongside goal failures",
            "Only comparable single-axis opposite outcomes form observed brackets",
            "Scene configuration/XML and robot code/assets must be checked before actual replay",
            "This is a regression evidence asset, not an executed regression suite",
        ],
    }
    if _has_secret(memory):
        raise ValueError("credential-like content in memory; export refused")
    return memory


def _has_secret(value):
    if isinstance(value, dict):
        return any(str(k).lower() in SECRET_KEYS or _has_secret(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_secret(v) for v in value)
    return isinstance(value, str) and bool(re.search(r"\bsk-[A-Za-z0-9_-]{16,}", value))


def _safe_export_file(path):
    if path.suffix == ".json":
        values = [read_json(path)]
    elif path.suffix == ".jsonl":
        values = _rows(path)
    else:
        return
    if any(_has_secret(value) for value in values):
        raise ValueError("credential-like content in evidence; export refused")


def _copy_checked(source, destination, expected):
    h = hashlib.sha256()
    pending = None
    try:
        with (
            source.open("rb") as src,
            tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".copy-", delete=False
            ) as dst,
        ):
            pending = Path(dst.name)
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                h.update(chunk)
                dst.write(chunk)
        if h.hexdigest() != expected:
            raise ValueError("source_changed_during_export")
        if destination.exists():
            raise FileExistsError(destination)
        pending.replace(destination)
        pending = None
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _reproduction_note(case):
    spec = case["reproduction"]
    notice = (
        "재실행은 수행하지 않았습니다. 원본 code/model/resource 해시를 먼저 확인하세요.\n"
        "scene2test 디렉터리에서 실행하며 CASE_DIR/GROOT_ROOT를 현재 위치로 대체하세요.\n"
        "--live는 별도 유료 API 호출이며 동일 응답/결과 재현을 보장하지 않습니다.\n"
        "목표·관측·기술·물리·시간 처리 조건을 변경하면 다른 로봇 실험입니다.\n\n"
    )
    if (
        case["parameters"] is None
        or spec["http_read_timeout_s"] is None
        or type(spec["push_enabled"]) is not bool
    ):
        return notice + "실행 계약/장면 정보가 부족해 재실행 명령을 생성하지 않았습니다.\n"
    argv = [
        "uv",
        "run",
        "--no-sync",
        "python",
        "tools/run_robot_goal_agent.py",
        "--scene-config",
        "{CASE_DIR}/scene_config.json",
        "--groot-root",
        "{GROOT_ROOT}",
        "--evaluation-profile",
        "goal_outcome_v1",
        "--navigation-completion",
        spec["navigation_completion"],
        "--max-calls",
        str(spec["max_calls"]),
        "--response-timeout",
        str(spec["http_read_timeout_s"]),
    ]
    if spec["policy_origin"] == "openai_api":
        if not isinstance(spec["model"], str):
            return notice + "모델 식별 누락: 재실행 명령 없음.\n"
        argv.extend(["--live", "--model=" + spec["model"]])
    if spec["push_enabled"]:
        argv.append("--enable-push")
    if spec["max_simulation_s"] is not None:
        argv.extend(["--max-seconds", str(spec["max_simulation_s"])])
    return notice + shlex.join(argv) + "\n"


def export_failure_memory(output: Path, memory, *, include_video=False):
    """Selective portable evidence, with explicit external dependencies and no API transcripts."""
    output = output.resolve()
    sources = [e["record"]["source"]["path"] for e in memory["episodes"].values()]
    sources.extend(row["source"] for row in memory["excluded"])
    if any(output.is_relative_to(Path(path).resolve()) for path in sources):
        raise ValueError("output must not be inside a source run")
    selected = {}
    # Preflight before creating any directory, including credentials and artifact freshness.
    for eid, item in memory["episodes"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", eid):
            raise ValueError("unsafe evidence ID")
        record = EpisodeRecord.model_validate(item["record"])
        root = Path(record.source.path).resolve()
        names = [
            name
            for name in record.artifact_hashes
            if (
                name in COPY_FILES
                or COPY_PATTERN.fullmatch(name)
                or (include_video and name == "rollout.mp4")
            )
        ]
        for name in names:
            path = root / name
            if (
                not path.resolve().is_relative_to(root)
                or _hash_file(path) != record.artifact_hashes[name]
            ):
                raise ValueError("source_changed_before_export")
            _safe_export_file(path)
        selected[eid] = names
    for case in memory["cases"]:
        if not re.fullmatch(r"[0-9a-f]{64}", case["case_id"]):
            raise ValueError("unsafe case ID")
    output.mkdir(parents=True, exist_ok=False)
    for eid, item in memory["episodes"].items():
        root = Path(item["record"]["source"]["path"])
        target = output / "evidence" / eid
        target.mkdir(parents=True)
        for name in selected[eid]:
            _copy_checked(root / name, target / name, item["record"]["artifact_hashes"][name])
        _json(target / "behavior.json", item["behavior"])
    for case in memory["cases"]:
        target = output / "cases" / case["case_id"]
        target.mkdir(parents=True)
        _json(target / "case.json", case)
        (target / "REPRODUCE.txt").write_text(_reproduction_note(case), encoding="utf-8")
        if case["parameters"] is not None:
            _json(target / "scene_config.json", case["parameters"])
    _json(output / "memory.json", memory)
    from failure_client.reporting.behavior_report import write_behavior_report

    write_behavior_report(output, memory, include_video=include_video)
    _json(
        output / "manifest.json",
        {
            "schema_version": "failure-memory-export-v1",
            "video_copied": include_video,
            "standalone_robot_environment": False,
            "api_transcripts_exported": False,
            "artifacts": [
                {"path": str(p.relative_to(output)), "sha256": _hash_file(p)}
                for p in sorted(output.rglob("*"))
                if p.is_file()
            ],
        },
    )
    return output / "index.html"
