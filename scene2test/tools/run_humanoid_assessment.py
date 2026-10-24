"""Run a separately frozen humanoid assessment with immediate terminal summaries."""

import argparse
import json
import threading
import time
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.afs_autonomous import stamp
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import PairedDesign, PairedDiscovery, paired_plan
from failure_client.reporting.humanoid_assessment import (
    LABELS,
    build_summary,
    export_summary,
    snapshot,
    terminal,
)
from llm_afs.behavior import digest
from robot_vlm.debug_log import clean

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT / "development/humanoid_assessment_10_20261023_v1"
DEFAULT_CONFIG = PROJECT / "config/humanoid_vulnerability_10_pro.json"
DEFAULT_CONTROL = Path(
    "/workspace/g1_failure/runtime/humanoid_crossing_openrouter/20261023T005929_285349Z"
)


def cached_measurements(root, states):
    path = Path(root) / "assessment_measurements.json"
    if not path.exists():
        return None
    wrapped = read_json(path)
    value = wrapped["value"]
    if wrapped.get("sha256") != digest(value):
        raise ValueError("assessment measurement cache digest mismatch")
    if value["checkpoint_sha256"] != [digest(s) for s in states]:
        return None
    return value["canonical"]


def main(argv=None, *, factory=PairedDiscovery):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="op", required=True)
    for op in ("plan", "init"):
        p = commands.add_parser(op)
        p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        p.add_argument("--run", type=Path, default=DEFAULT_CONTROL)
        p.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    for op in ("run", "status", "report"):
        p = commands.add_parser(op)
        p.add_argument("--assessment", type=Path, default=DEFAULT_ROOT)
        if op == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-new-attempts", type=int)
            p.add_argument("--max-new-afs-requests", type=int)
            p.add_argument("--continue-after-exclusion", action="store_true")
        if op == "report":
            p.add_argument("--verify-safety", action="store_true")
    args = parser.parse_args(argv)
    if args.op in {"plan", "init"}:
        design = PairedDesign.model_validate(read_json(args.config))
        if design.purpose != "robot-vulnerability-assessment":
            raise ValueError("explicit robot-vulnerability-assessment design required")
        wrapped = paired_plan([args.run], design)
        m = wrapped["manifest"]
        print(
            "ASSESSMENT_PLAN="
            + json.dumps(
                {
                    k: m[k]
                    for k in (
                        "valid_total",
                        "attempt_cap_total",
                        "robot_api_call_upper_bound",
                        "afs_request_upper_bound",
                        "methods",
                        "bootstrap",
                    )
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.op == "init":
            factory.create(args.output_dir, wrapped)
            print(f"ASSESSMENT={args.output_dir.resolve()}; no API or robot launched", flush=True)
        return 0
    root = args.assessment.resolve()
    manifest, states = snapshot(root)
    canonical = cached_measurements(root, states)
    initial = build_summary(root, manifest, states, canonical=canonical)
    error, interrupted = None, False
    progress = {"stage": "준비", "started": time.monotonic()}
    stop = threading.Event()

    def event(value):
        kind, detail = value["event"], value.get("detail", {})
        if kind == "proposal_intent":
            progress.update(stage=f"AFS 제안 생성 중 ({detail['id']})", started=time.monotonic())
            print(progress["stage"], flush=True)
        elif kind == "rollout_intent":
            progress.update(stage=f"로봇 테스트 실행 중 ({detail['id']})", started=time.monotonic())
            print(progress["stage"], flush=True)
        elif kind == "observed":
            # Display failures immediately, before the executor's heavier aggregate checks.
            print(
                f"테스트 결과: {value['method']}/{detail['id']} "
                f"{detail['status']} {detail['outcome']}",
                flush=True,
            )
            try:
                m, saved = snapshot(root)
                partial = build_summary(root, m, saved)
                case = next(
                    c
                    for c in partial["cases"]
                    if c["attempt_id"] == detail["id"]
                    and c["method"] == value["method"]
                    and c["seed"] == value["seed"]
                )
                print(
                    f"누적 {partial['attempted']}/{m['attempt_cap_total']}시도 | "
                    f"PASS {partial['pass']} FAIL {partial['fail']} 제외 {partial['excluded']}",
                    flush=True,
                )
                if case["primary_family"]:
                    print(
                        "검출 유형: " + LABELS.get(case["primary_family"], case["primary_family"]),
                        flush=True,
                    )
                if case["changes"]:
                    print(
                        "변경: "
                        + ", ".join(
                            f"{c['axis']} {c['before']:.4g}→{c['after']:.4g}"
                            for c in case["changes"]
                        ),
                        flush=True,
                    )
                if partial["valid"] == partial["target_valid"]:
                    print("=== 최종 검증 전 핵심 결과 · 안전 측정 집계 중 ===", flush=True)
                    print(terminal(partial), flush=True)
            except (ValueError, OSError, KeyError) as exc:
                print("즉시 요약 보류: " + clean(str(exc)), flush=True)
            progress.update(stage="측정·이력 검증 중", started=time.monotonic())

    def heartbeat():
        while not stop.wait(30):
            print(
                f"진행 중: {progress['stage']} | 현재 단계 경과 "
                f"{time.monotonic() - progress['started']:.0f}초",
                flush=True,
            )

    try:
        if args.op == "run" and not initial["complete"]:
            if not args.live:
                raise ValueError("실제 실행에는 --live가 필요합니다")
            attempts = (
                manifest["attempt_cap_total"]
                if args.max_new_attempts is None
                else args.max_new_attempts
            )
            requests = (
                manifest["afs_request_upper_bound"]
                if args.max_new_afs_requests is None
                else args.max_new_afs_requests
            )
            if attempts < 1 or requests < 1:
                raise ValueError("실행/AFS 요청 한도는 1 이상이어야 합니다")
            threading.Thread(target=heartbeat, daemon=True).start()
            campaign = factory(root, on_event=event)
            canonical = campaign.run(
                live=True,
                max_new_attempts=attempts,
                max_new_afs_requests=requests,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        elif args.op == "report" and args.verify_safety:
            print("저장 근거의 안전 측정을 검증합니다. 새 API/로봇 실행은 없습니다.", flush=True)
            threading.Thread(target=heartbeat, daemon=True).start()
            progress["stage"] = "저장 안전 측정 검증 중"
            canonical = factory(root).summary()
    except KeyboardInterrupt:
        interrupted = True
        error = {"type": "KeyboardInterrupt", "message": "사용자 중단; 원본 intent와 결과 보존"}
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        error = {"type": type(exc).__name__, "message": clean(str(exc))}
    finally:
        stop.set()
    manifest, states = snapshot(root)
    if canonical is not None:
        # Only use measurements computed for the exact current durable state.
        if error is None:
            value = {
                "checkpoint_sha256": [digest(s) for s in states],
                "canonical": {"dynamic_human_safety": canonical.get("dynamic_human_safety", {})},
            }
            atomic_json(
                root / "assessment_measurements.json", {"value": value, "sha256": digest(value)}
            )
        else:
            canonical = cached_measurements(root, states)
    summary = build_summary(root, manifest, states, canonical=canonical, error=error)
    print(terminal(summary), flush=True)
    if args.op != "status":
        path = export_summary(root / "assessment_reports" / stamp(), summary)
        print(f"REPORT={path}", flush=True)
        print(f"SUMMARY_JSON={path.parent / 'summary.json'}", flush=True)
    return (
        130
        if interrupted
        else 0
        if summary["complete"]
        or (args.op == "status" and summary["status"] in {"READY", "INCOMPLETE"})
        else 2
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print("ASSESSMENT_STOPPED=" + clean(str(exc)), flush=True)
        raise SystemExit(2) from None
