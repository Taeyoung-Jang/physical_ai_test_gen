"""Deterministic, evidence-bound robot vulnerability summaries; no reporting LLM."""

import hashlib
import json
import os
import sqlite3
from collections import Counter
from html import escape
from pathlib import Path

from failure_client.experiments.local_goal_adapter import atomic_json
from llm_afs.behavior import digest

LABELS = {
    "goal_occupied": "목표 영역 점유",
    "fall": "넘어짐",
    "collision": "충돌",
    "manipulation_failure": "조작 동작 실패",
    "locomotion_stall": "이동 정체",
    "obstacle_interference": "장애물 간섭",
    "goal_completion_failure": "목표 체류 미완료",
    "goal_endpoint_rejection": "목표점 경로 거절",
    "subgoal_completion_loop": "중간 목표 반복",
}
VERSION = "humanoid-vulnerability-summary-v1"
DESCRIPTIONS = {
    "goal_occupied": "물체가 목표 영역을 덮고 종료 직전 로봇이 정체한 장면입니다.",
    "fall": "자세 기록에서 지속적인 낮은 몸통 높이 또는 큰 기울기가 검출됐습니다.",
    "collision": "종료 직전 정체와 지정된 세계 물체 접촉 기준이 함께 검출됐습니다.",
    "manipulation_failure": (
        "마지막 조작 요청이 실패·거절됐습니다. 실제 힘 부족을 확정한 것은 아닙니다."
    ),
    "locomotion_stall": "이동 명령을 실행한 구간에서 지속적인 저이동 조건이 검출됐습니다.",
    "obstacle_interference": "장애물 근처 정체와 반복된 경로 차단 기록이 함께 검출됐습니다.",
    "goal_completion_failure": "목표 영역 안에서 요구된 체류를 완료하지 못했습니다.",
}
AXIS_LABELS = {
    "box_mass_kg": "상자 무게(kg)",
    "box_friction": "상자 마찰",
    "floor_friction": "바닥 마찰",
    "corridor_width_m": "통로 폭(m)",
    "box_lateral_fraction": "상자 좌우 위치(비율)",
    "box_goal_x_m": "상자 전후 위치(m)",
    "human_x_m": "사람 전후 위치(m)",
    "human_speed_mps": "사람 속도(m/s)",
    "human_trigger_distance_m": "사람 출발 거리(m)",
}


def checkpoint(root):
    """Read a saved checkpoint without initializing/migrating its database."""
    uri = (Path(root).resolve() / "campaign.sqlite3").as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        row = db.execute("SELECT payload,sha256 FROM research_state WHERE id=1").fetchone()
    if row is None:
        raise ValueError("missing assessment checkpoint")
    state = json.loads(row[0])
    if digest(state) != row[1]:
        raise ValueError("assessment checkpoint digest mismatch")
    return state


def snapshot(root):
    """Verify manifest/checkpoint bindings and small core artifacts before display."""
    root = Path(root).resolve()
    wrapped = json.loads((root / "manifest.json").read_text())
    manifest = wrapped["manifest"]
    if wrapped["sha256"] != digest(manifest):
        raise ValueError("assessment manifest digest mismatch")
    if manifest["design"]["purpose"] != "robot-vulnerability-assessment":
        raise ValueError("use a separately frozen robot vulnerability assessment")
    if manifest["methods"] != ["afs"]:
        raise ValueError("this assessment is AFS only; no Random dispatch authorized")
    parent = checkpoint(root)
    if parent["manifest_sha256"] != wrapped["sha256"]:
        raise ValueError("assessment parent binding changed")
    states = []
    for seed in manifest["design"]["seeds"]:
        for method in manifest["methods"]:
            arm_root = root / "seeds" / str(seed) / method
            state = checkpoint(arm_root)
            plan = state["lock"]["plan"]
            protocol = json.loads((arm_root / "protocol.json").read_text())
            if (
                state["lock_sha256"] != digest(state["lock"])
                or protocol != {"lock": state["lock"], "lock_sha256": state["lock_sha256"]}
                or state["lock"]["plan"]["manifest_sha256"] != wrapped["sha256"]
            ):
                raise ValueError("assessment arm binding changed")
            if (
                plan["method"] != method
                or plan["seed"] != seed
                or plan["budget"] != manifest["design"]["search"]
                or plan["target_config"] != manifest["robot_config"]
                or plan.get("matched_local") != manifest["design"]["matched_local"]
            ):
                raise ValueError("assessment robot/budget/base binding changed")
            for attempt in state["attempts"]:
                episode = attempt.get("episode")
                if episode is None:
                    continue
                archive = Path(episode["source"]["path"])
                expected = arm_root / "attempts" / attempt["id"] / "rollout"
                if archive.resolve() != expected.resolve():
                    raise ValueError("assessment episode points outside its own arm")
                for name in ("result.json", "protocol.json", "decisions.jsonl"):
                    expected_hash = episode.get("artifact_hashes", {}).get(name)
                    if expected_hash is None and episode["status"] != "VALID":
                        continue  # Partial exclusions stay unknown, never become valid results.
                    path = archive / name
                    if (
                        not path.is_file()
                        or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
                    ):
                        raise ValueError("assessment core evidence changed")
                if episode["status"] == "VALID":
                    result = json.loads((archive / "result.json").read_text())
                    if result.get("task_outcome") != episode["task_outcome"]:
                        raise ValueError("saved outcome differs from raw result")
            states.append(state)
    return manifest, states


def tool_issues(episode):
    path = Path(episode["source"]["path"]) / "decisions.jsonl"
    if not path.is_file():
        return None
    issues, actions = Counter(), {}
    for line in path.open():
        row = json.loads(line)
        version = row.get("observation_version")
        if "action" in row:
            actions[version] = row["action"]["action"]
        if row.get("event") != "tool_result":
            continue
        result = row["result"]
        status = result.get("status")
        if status in {
            "rejected",
            "failed",
            "aborted",
            "blocked_endpoint",
            "no_path",
            "recovery_connector_blocked",
            "no_tracking_clearance",
        }:
            issues[(actions.get(version), status, result.get("reason"))] += 1
    return [{"action": a, "status": s, "reason": r, "count": n} for (a, s, r), n in issues.items()]


def build_summary(root, manifest, states, *, canonical=None, error=None):
    design = manifest["design"]
    attempts = [(s["lock"]["plan"], a) for s in states for a in s["attempts"]]
    rows = [(p, a, a["episode"]) for p, a in attempts if "episode" in a]
    valid = [(p, a, e) for p, a, e in rows if e["status"] == "VALID"]
    failures = [(p, a, e) for p, a, e in valid if e["task_outcome"] == "FAIL"]
    safety = {}
    if canonical is not None:
        for arm in canonical.get("dynamic_human_safety", {}).get("arms", []):
            for entry in arm.get("evidence", []):
                measurement = entry["measurement"]
                if (
                    measurement.get("measurement_status") == "AVAILABLE"
                    and measurement.get("evidence_id") == entry["evidence_id"]
                    and type(measurement.get("safety_event_detected")) is bool
                    and measurement.get("evidence_binding")
                    == "VERIFIED_ARCHIVE_DYNAMIC_SCENE_BASE_AND_CONTACT_TRACE"
                ):
                    safety[entry["evidence_id"]] = measurement
    cases, coverage, valid_coverage, family_counts = [], Counter(), Counter(), Counter()
    for _, attempt in attempts:
        coverage.update(attempt["candidate"].get("changed_axes", []))
    for plan, attempt, episode in rows:
        candidate = attempt["candidate"]
        changed = candidate.get("changed_axes", [])
        if episode["status"] == "VALID":
            valid_coverage.update(changed)
        family = (episode.get("attribution") or {}).get("primary_family")
        rule = ((episode.get("taxonomy") or {}).get("families") or {}).get(family, {})
        if rule.get("status") != "DETECTED" or rule.get("rule_version") != (
            episode.get("attribution") or {}
        ).get("rule_version"):
            family = None
        goal_fail = episode["status"] == "VALID" and episode["task_outcome"] == "FAIL"
        if goal_fail and family:
            family_counts[family] += 1
        base = design["matched_local"]["base_parameters"]
        measurement = safety.get(episode["evidence_id"])
        if measurement is not None and measurement.get("task_outcome") != episode["task_outcome"]:
            measurement = None
            safety.pop(episode["evidence_id"])
        cases.append(
            {
                "attempt_id": attempt["id"],
                "method": plan["method"],
                "seed": plan["seed"],
                "status": episode["status"],
                "task_outcome": episode["task_outcome"],
                "termination_reason": episode.get("termination_reason"),
                "primary_family": family if goal_fail else None,
                "label": LABELS.get(family, "목표 미달 · 주 실패 유형 미확정")
                if goal_fail
                else None,
                "description": DESCRIPTIONS.get(
                    family,
                    "목표 미달은 확인됐으나 지원하는 규칙으로 주 실패 유형을 확정하지 못했습니다.",
                )
                if goal_fail
                else None,
                "changes": [
                    {"axis": axis, "before": base[axis], "after": candidate["parameters"][axis]}
                    for axis in changed
                ],
                "final_goal_distance_m": (episode.get("measures") or {}).get(
                    "last_sample_goal_distance_m"
                ),
                "robot_api_calls": episode.get("robot_api_calls"),
                "evidence_id": episode["evidence_id"],
                "video": str(Path(episode["source"]["path"]) / "rollout.mp4"),
                "safety": None
                if measurement is None
                else {
                    k: measurement.get(k)
                    for k in (
                        "safety_event_detected",
                        "contact_steps",
                        "minimum_center_distance_m",
                        "longest_continuous_exposure_s",
                    )
                },
                "causal_status": "UNCONFIRMED",
                "tool_issues": tool_issues(episode),
            }
        )
    measured = [e for _, _, e in valid if e["evidence_id"] in safety]
    target = manifest["valid_total"]
    complete = len(valid) == target and all(
        s["status"] in {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"} for s in states
    )
    baseline_bad = any(
        s["attempts"]
        and s["attempts"][0].get("episode", {}).get("status") is not None
        and (
            s["attempts"][0]["episode"]["status"] != "VALID"
            or s["attempts"][0]["episode"]["task_outcome"] != "PASS"
        )
        for s in states
    )
    status = (
        "BASELINE_NOT_CONFIRMED"
        if baseline_bad
        else "COMPLETE"
        if complete
        else "NEEDS_ATTENTION"
        if error or any(s["status"] == "NEEDS_ATTENTION" for s in states)
        else "VERIFYING"
        if len(valid) == target
        else "READY"
        if not attempts
        else "INCOMPLETE"
    )
    return {
        "schema_version": VERSION,
        "assessment": str(Path(root).resolve()),
        "status": status,
        "complete": complete,
        "target_valid": target,
        "attempted": len(attempts),
        "valid": len(valid),
        "pass": sum(e["task_outcome"] == "PASS" for _, _, e in valid),
        "fail": len(failures),
        "excluded": sum(e["status"] != "VALID" for _, _, e in rows),
        "pending": len(attempts) - len(rows),
        "pending_proposals": sum(
            (s.get("pending") or {}).get("kind") == "proposal" for s in states
        ),
        "observed_failure_rate": len(failures) / len(valid) if valid else None,
        "afs_requests": sum(len(s["proposals"]) for s in states),
        "robot_api_calls_observed": sum(e.get("robot_api_calls", 0) for _, _, e in rows),
        "family_counts": dict(family_counts),
        "cases": cases,
        "safety": {
            "measurement_status": "PENDING_OR_UNKNOWN"
            if len(measured) != len(valid)
            else "AVAILABLE"
            if measured
            else "NO_VALID_EPISODES",
            "measured": len(measured),
            "unknown": len(valid) - len(measured),
            "events": sum(bool(safety[e["evidence_id"]]["safety_event_detected"]) for e in measured)
            if measured
            else None,
            "scope": "Separate contact/protected-zone event, including goal PASS",
        },
        "coverage": {
            "attempted_axes": dict(coverage),
            "valid_axes": dict(valid_coverage),
            "untested_axes": sorted(set(manifest["domain_axes"]) - set(valid_coverage)),
        },
        "robot": manifest["robot_config"],
        "error": error,
        "claims": [
            "Recorded operational detections, not established physical root causes",
            "Targeted tests of this fixed task/domain, not general robot failure probability",
            "Exclusions and unknown safety measurements are not robot failures or safe results",
            "No new AFS versus Random superiority claim from this assessment",
        ],
        "checkpoint_sha256": [digest(s) for s in states],
    }


def terminal(summary):
    lines = [
        "=== 휴머노이드 취약점 평가 ===",
        "범위: 지정된 작업·환경·Agent/제어기 조건의 관측 결과",
        f"상태: {summary['status']} | 유효 {summary['valid']}/{summary['target_valid']}"
        f" | 시도 {summary['attempted']} | 진행 중 {summary['pending']}",
        f"목표 PASS {summary['pass']} / FAIL {summary['fail']} / 제외 {summary['excluded']}",
        f"AFS 요청 {summary['afs_requests']}회 | "
        f"로봇 API 호출 {summary['robot_api_calls_observed']}회",
    ]
    failures = [
        c for c in summary["cases"] if c["status"] == "VALID" and c["task_outcome"] == "FAIL"
    ]
    if not failures:
        lines.append("목표 실패 미검출: 이 테스트 범위의 결과이며 무결함을 의미하지 않습니다.")
    for case in failures:
        changes = (
            ", ".join(
                f"{AXIS_LABELS.get(c['axis'], c['axis'])}: {c['before']:.4g} → {c['after']:.4g}"
                for c in case["changes"]
            )
            or "기준 장면"
        )
        distance = case["final_goal_distance_m"]
        distance = f"{distance:.3f}m" if distance is not None else "미확인"
        lines += [
            f"- {case['method']}/{case['attempt_id']}: {case['label']}",
            f"  해석: {case['description']}",
            f"  조건: {changes}",
            f"  관측: {case['termination_reason']} | 최종 목표 거리 {distance}",
        ]
        for issue in case["tool_issues"] or []:
            lines.append(
                f"  도구 기록: {issue['action']} {issue['status']}"
                f" {issue['reason'] or ''} ({issue['count']}회; 원인 확정 아님)"
            )
        lines.append(f"  영상: {case['video']}")
    safety = summary["safety"]
    lines.append(
        f"사람 안전 이벤트: 측정 {safety['measured']}회, 이벤트 {safety['events']}"
        f", 미확인 {safety['unknown']}회 (목표 PASS와 별도)"
    )
    lines.append(f"유효 실행에서 변경하지 않은 축: {len(summary['coverage']['untested_axes'])}개")
    for case in summary["cases"]:
        if case["status"] != "VALID":
            lines.append(
                f"제외: {case['attempt_id']} · {case['termination_reason']} (목표 실패에 미포함)"
            )
    if summary["pending_proposals"]:
        lines.append("미완료 제안 요청이 남아 있습니다. 저장 응답 수집 없이 재전송하지 않습니다.")
    if summary["error"]:
        lines.append(f"실행 중단: {summary['error']['type']}: {summary['error']['message']}")
    lines.append(
        "판정 범위: 관측된 취약 장면이며 물리적 원인·일반 성능·통계적 우위는 미확정입니다."
    )
    return "\n".join(lines)


def export_summary(output, summary):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "summary.json", summary)
    text = terminal(summary)
    (output / "summary.txt").write_text(text + "\n")
    links = "".join(
        '<li><a href="'
        + escape(os.path.relpath(c["video"], output), quote=True)
        + '">'
        + escape(c["method"] + "/" + c["attempt_id"])
        + "</a></li>"
        for c in summary["cases"]
    )
    (output / "report.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        "<title>휴머노이드 취약점 평가</title><body><pre>"
        + escape(text)
        + "</pre><h2>실행 영상</h2><ul>"
        + links
        + "</ul><details><summary>측정 근거</summary><pre>"
        + escape(json.dumps(summary, ensure_ascii=False, indent=2))
        + "</pre></details></body></html>"
    )
    atomic_json(
        output / "manifest.json",
        {
            "artifacts": [
                {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(output.iterdir())
                if p.is_file()
            ]
        },
    )
    return output / "report.html"
