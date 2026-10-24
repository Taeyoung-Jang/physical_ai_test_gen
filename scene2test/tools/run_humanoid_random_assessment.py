"""Separate local Random assessment; leaves frozen AFS executable sources unchanged."""

import argparse
import copy
import hashlib
import json
import os
import threading
import time
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from clear_path.search_domain import checked_domain
from failure_client.evaluation.goal_run_reader import read_json
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.experiments.afs_autonomous import stamp
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import (
    MODE as ARM_MODE,
)
from failure_client.experiments.paired_discovery import (
    PairedDesign,
    PairedDiscovery,
    paired_fingerprint,
    paired_plan,
)
from failure_client.experiments.research_protocol import CampaignConfig
from failure_client.reporting.humanoid_assessment import (
    build_summary,
    checkpoint,
    terminal,
)
from failure_client.storage.research_store import ResearchStore
from llm_afs.behavior import digest
from robot_vlm.debug_log import clean

PROJECT = Path(__file__).resolve().parents[1]
VERSION = "humanoid-random-assessment-v1"
PURPOSE = "robot-random-vulnerability-assessment"
DEFAULT_ROOT = PROJECT / "development/humanoid_random_assessment_10_20261023_v1"
DEFAULT_CONFIG = PROJECT / "config/humanoid_random_vulnerability_10_pro.json"
DEFAULT_CONTROL = Path(
    "/workspace/g1_failure/runtime/humanoid_crossing_openrouter/20261023T005929_285349Z"
)


class RandomDesign(PairedDesign):
    schema_version: Literal["humanoid-random-assessment-design-v1"] = (
        "humanoid-random-assessment-design-v1"
    )
    purpose: Literal["robot-random-vulnerability-assessment"] = PURPOSE
    methods: list[Literal["random"]] = Field(default_factory=lambda: ["random"])
    afs_requests_per_seed: Literal[0] = 0

    @model_validator(mode="after")
    def coherent(self):
        if self.methods != ["random"] or self.matched_local is None:
            raise ValueError("Random-only assessment requires one Random arm and fixed local base")
        # Reuse the unchanged shared task/domain/budget validation, not its AFS dispatch.
        PairedDesign.model_validate(validation_template(self.model_dump()))
        return self


def validation_template(data):
    value = copy.deepcopy(data)
    value.update(
        schema_version="paired-trajectory-design-v1",
        purpose="robot-vulnerability-assessment",
        methods=["afs"],
        afs_requests_per_seed=1,
    )
    return value


def fingerprint(config):
    result = paired_fingerprint(config)
    result["source_hashes"]["tools/run_humanoid_random_assessment.py"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    return result


def plan(paths, design, *, fingerprint_fn=None):
    design = RandomDesign.model_validate(design.model_dump())
    template = PairedDesign.model_validate(validation_template(design.model_dump()))
    wrapped = paired_plan(paths, template, fingerprint_fn=fingerprint_fn or fingerprint)
    manifest = wrapped["manifest"]
    manifest.update(
        schema_version=VERSION,
        design=design.model_dump(),
        methods=["random"],
        afs_request_upper_bound=0,
        method_assignment="Random only; no AFS proposer or history-guided selection",
        execution_order="predeclared seeds and local attempt indices",
        random_distribution="uniform axis subsets and admissible values; alternating "
        "one/two changes from the same fixed base, no outcome/geometry filtering",
        limits=[
            "Standalone local Random development assessment, not AFS comparison",
            "Baseline and every new execution consume the fixed budget",
            "Exclusions stop and consume attempts; no retry/replacement",
            "Zero AFS proposer calls; GPT robot policy calls are still required",
            "Operational detections are not established physical root causes",
        ],
    )
    return {"manifest": manifest, "sha256": digest(manifest)}


def checked_manifest(wrapped):
    m = wrapped["manifest"]
    if wrapped.get("sha256") != digest(m) or m.get("schema_version") != VERSION:
        raise ValueError("Random assessment manifest changed")
    design = RandomDesign.model_validate(m["design"])
    cfg = CampaignConfig.model_validate(m["robot_config"])
    axes = checked_domain(design.scene_domain, cfg.scene_schema)
    from failure_client.evaluation.dynamic_human_safety import CONTRACT

    if m["domain_axes"] != axes and digest(m["domain_axes"]) != digest(axes):
        raise ValueError("Random domain axes differ")
    if (
        m["domain_id"] != digest({"schema": cfg.scene_schema, "axes": axes})
        or m.get("secondary_measurement")
        != (dict(CONTRACT) if design.secondary_measurement else None)
        or m["execution_origin"]
        not in {
            "mock",
            "openrouter_api" if cfg.robot.api_provider == "openrouter" else "openai_api",
        }
        or digest(m["evaluators"])
        != digest(
            {
                "primary": metric_options(cfg.scene_schema, "system-twelve-v1"),
                "original_six": metric_options(cfg.scene_schema),
            }
        )
    ):
        raise ValueError("Random robot/measurement contract differs")
    n = len(design.seeds)
    if (
        m["methods"] != ["random"]
        or m["afs_request_upper_bound"] != 0
        or m["valid_total"] != n * design.valid_per_arm
        or m["attempt_cap_total"] != n * design.attempts_per_arm
        or m["robot_api_call_upper_bound"]
        != n * design.attempts_per_arm * m["robot_config"]["robot"]["max_calls"]
        or m["matched_local"] != design.matched_local
        or m["scene_domain"] != design.scene_domain
        or m["external_history_in_evaluation"] != []
    ):
        raise ValueError("Random-only budget/domain/history binding changed")
    return m


def no_proposer(*_, **__):
    raise RuntimeError("Random assessment must never invoke an AFS proposer")


class RandomAssessment(PairedDiscovery):
    def __init__(self, root, *, runner=None, proposer=None, fingerprint_fn=None, on_event=None):
        self.root = Path(root).resolve()
        self.wrapped = read_json(self.root / "manifest.json")
        self.manifest = checked_manifest(self.wrapped)
        self.design = RandomDesign.model_validate(self.manifest["design"])
        if not (self.root / "campaign.sqlite3").is_file():
            raise ValueError("initialize a new Random assessment first")
        self.store = ResearchStore(self.root)
        state, _ = self.store.load()
        if state != {"mode": VERSION, "manifest_sha256": self.wrapped["sha256"]}:
            raise ValueError("Random assessment parent binding changed")
        self.kwargs = {
            "runner": runner,
            "proposer": proposer or no_proposer,
            "fingerprint_fn": fingerprint_fn or fingerprint,
        }
        self.on_event = on_event

    @classmethod
    def create(cls, root, wrapped, *, fingerprint_fn=None):
        m = checked_manifest(wrapped)
        paths = [r["source"]["path"] for r in m["control_provenance"]]
        expected = plan(
            paths, RandomDesign.model_validate(m["design"]), fingerprint_fn=fingerprint_fn
        )
        if digest(expected) != digest(wrapped):
            raise ValueError("Random preparation/source/resources changed")
        root = Path(root).resolve()
        if any(
            root.is_relative_to(Path(p).resolve()) or Path(p).resolve().is_relative_to(root)
            for p in paths
        ):
            raise ValueError("Random output overlaps reference archives")
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "manifest.json", wrapped)
        ResearchStore(root).save(
            {"mode": VERSION, "manifest_sha256": wrapped["sha256"]}, -1, "created"
        )
        for seed in m["design"]["seeds"]:
            arm_root = root / "seeds" / str(seed) / "random"
            arm_root.mkdir(parents=True, exist_ok=False)
            arm_plan = {
                "mode": ARM_MODE,
                "history": [],
                "seed": seed,
                "method": "random",
                "cold_start_per_seed": 1,
                "budget": m["design"]["search"],
                "target_config": m["robot_config"],
                "condition_id": m["reference_condition_id"],
                "geometry_id": m["reference_geometry_id"],
                "execution_origin": m["execution_origin"],
                "robot_api_call_upper_bound": m["design"]["attempts_per_arm"]
                * m["robot_config"]["robot"]["max_calls"],
                "afs_request_upper_bound": 0,
                "manifest_sha256": wrapped["sha256"],
                "limits": m["limits"],
                "scene_domain": m["scene_domain"],
                "matched_local": m["matched_local"],
            }
            lock = {"plan": arm_plan, "environment": m["environment"]}
            atomic_json(arm_root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
            ResearchStore(arm_root).save(
                {
                    "schema_version": ARM_MODE,
                    "lock": lock,
                    "lock_sha256": digest(lock),
                    "status": "READY",
                    "reason": None,
                    "pending": None,
                    "selected": None,
                    "attempts": [],
                    "proposals": [],
                },
                -1,
                "created",
            )
        return root


def snapshot(root):
    root = Path(root).resolve()
    wrapped = read_json(root / "manifest.json")
    m = checked_manifest(wrapped)
    if checkpoint(root) != {"mode": VERSION, "manifest_sha256": wrapped["sha256"]}:
        raise ValueError("Random assessment checkpoint binding changed")
    states = []
    for seed in m["design"]["seeds"]:
        arm_root = root / "seeds" / str(seed) / "random"
        state = checkpoint(arm_root)
        p = state["lock"]["plan"]
        if (
            state["lock_sha256"] != digest(state["lock"])
            or read_json(arm_root / "protocol.json")
            != {"lock": state["lock"], "lock_sha256": state["lock_sha256"]}
            or p["manifest_sha256"] != wrapped["sha256"]
            or p["method"] != "random"
            or p["seed"] != seed
            or p["history"]
            or state["proposals"]
            or p["afs_request_upper_bound"] != 0
            or p["budget"] != m["design"]["search"]
            or p["target_config"] != m["robot_config"]
            or p["scene_domain"] != m["scene_domain"]
            or p["matched_local"] != m["matched_local"]
        ):
            raise ValueError("Random arm/proposer/history binding changed")
        for a in state["attempts"]:
            e = a.get("episode")
            if e is None:
                continue
            archive = Path(e["source"]["path"])
            if archive.resolve() != (arm_root / "attempts" / a["id"] / "rollout").resolve():
                raise ValueError("Random record points outside its own arm")
            for name in ("result.json", "protocol.json", "decisions.jsonl"):
                expected = e.get("artifact_hashes", {}).get(name)
                if expected is None and e["status"] != "VALID":
                    continue
                path = archive / name
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("Random core evidence changed")
            if (
                e["status"] == "VALID"
                and read_json(archive / "result.json")["task_outcome"] != e["task_outcome"]
            ):
                raise ValueError("Random outcome differs from raw result")
        states.append(state)
    return m, states


def summary(root, *, canonical=None, error=None):
    m, states = snapshot(root)
    value = build_summary(root, m, states, canonical=canonical, error=error)
    value["method"] = "random"
    if value["afs_requests"]:
        raise ValueError("Random report cannot contain AFS proposal costs")
    return value


def export_random_summary(output, value):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "summary.json", value)
    text = "=== Random 전용 평가 · AFS 제안 0회 ===\n" + terminal(value)
    (output / "summary.txt").write_text(text + "\n")
    links = "".join(
        '<li><a href="'
        + escape(os.path.relpath(c["video"], output), quote=True)
        + '">'
        + escape(c["attempt_id"])
        + "</a></li>"
        for c in value["cases"]
    )
    (output / "report.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        "<title>Random 휴머노이드 취약점 평가</title><body><pre>"
        + escape(text)
        + "</pre><ul>"
        + links
        + "</ul><details><summary>측정 근거</summary><pre>"
        + escape(json.dumps(value, ensure_ascii=False, indent=2))
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


def main(argv=None, *, factory=RandomAssessment):
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
            p.add_argument("--continue-after-exclusion", action="store_true")
        if op == "report":
            p.add_argument("--verify-safety", action="store_true")
    args = parser.parse_args(argv)
    if args.op in {"plan", "init"}:
        wrapped = plan([args.run], RandomDesign.model_validate(read_json(args.config)))
        print(
            "RANDOM_PLAN="
            + json.dumps(
                {
                    k: wrapped["manifest"][k]
                    for k in (
                        "valid_total",
                        "attempt_cap_total",
                        "robot_api_call_upper_bound",
                        "afs_request_upper_bound",
                        "methods",
                    )
                }
            ),
            flush=True,
        )
        if args.op == "init":
            factory.create(args.output_dir, wrapped)
            print(f"ASSESSMENT={args.output_dir.resolve()}; no API/robot execution", flush=True)
        return 0
    root = args.assessment.resolve()
    manifest, states = snapshot(root)
    canonical, error, interrupted = None, None, False
    cache = root / "assessment_measurements.json"
    if cache.exists():
        wrapped = read_json(cache)
        if wrapped["sha256"] != digest(wrapped["value"]):
            raise ValueError("Random measurement cache changed")
        if wrapped["value"]["checkpoint_sha256"] == [digest(s) for s in states]:
            canonical = wrapped["value"]["canonical"]
    initial = build_summary(root, manifest, states, canonical=canonical)
    progress = {"stage": "준비", "started": time.monotonic()}
    stop = threading.Event()

    def event(value):
        kind, detail = value["event"], value.get("detail", {})
        if kind == "proposal_intent":
            raise RuntimeError("Random must never start an AFS request")
        if kind == "rollout_intent":
            progress.update(stage=f"Random 테스트 {detail['id']} 실행 중", started=time.monotonic())
            print(progress["stage"], flush=True)
        elif kind == "observed":
            print(f"Random 결과: {detail['id']} {detail['status']} {detail['outcome']}", flush=True)
            try:
                partial = summary(root)
                print(
                    f"누적 {partial['attempted']}/{manifest['attempt_cap_total']}시도 | "
                    f"PASS {partial['pass']} FAIL {partial['fail']} 제외 {partial['excluded']}",
                    flush=True,
                )
                case = next(
                    c
                    for c in partial["cases"]
                    if c["attempt_id"] == detail["id"] and c["seed"] == value["seed"]
                )
                print(
                    "변경: "
                    + (
                        ", ".join(
                            f"{c['axis']} {c['before']:.4g}→{c['after']:.4g}"
                            for c in case["changes"]
                        )
                        or "공통 기준 장면"
                    ),
                    flush=True,
                )
                if case["task_outcome"] == "FAIL":
                    print("관측: " + case["label"], flush=True)
                if partial["valid"] == partial["target_valid"]:
                    print("=== 최종 검증 전 핵심 결과 · 안전 측정 집계 중 ===", flush=True)
                    print(terminal(partial), flush=True)
            except (ValueError, OSError, KeyError) as exc:
                print("즉시 요약 보류: " + clean(str(exc)), flush=True)
            progress.update(stage="저장 결과 검증 중", started=time.monotonic())

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
                raise ValueError("실제 로봇 Agent 실행에는 --live가 필요합니다")
            cap = (
                manifest["attempt_cap_total"]
                if args.max_new_attempts is None
                else args.max_new_attempts
            )
            if cap < 1:
                raise ValueError("실행 한도는 1 이상이어야 합니다")
            threading.Thread(target=heartbeat, daemon=True).start()
            canonical = factory(root, on_event=event).run(
                live=True,
                max_new_attempts=cap,
                max_new_afs_requests=1,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        elif args.op == "report" and args.verify_safety:
            progress["stage"] = "안전 측정 검증 중 (새 API/로봇 실행 없음)"
            threading.Thread(target=heartbeat, daemon=True).start()
            canonical = factory(root).summary()
    except KeyboardInterrupt:
        interrupted = True
        error = {"type": "KeyboardInterrupt", "message": "사용자 중단; 원본 intent 보존"}
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        error = {"type": type(exc).__name__, "message": clean(str(exc))}
    finally:
        stop.set()
    _, states = snapshot(root)
    if canonical is not None and error is None:
        value = {
            "checkpoint_sha256": [digest(s) for s in states],
            "canonical": {"dynamic_human_safety": canonical.get("dynamic_human_safety", {})},
        }
        atomic_json(cache, {"value": value, "sha256": digest(value)})
    elif error:
        canonical = None
    result = summary(root, canonical=canonical, error=error)
    print("=== Random 전용 평가 · AFS 제안 0회 ===", flush=True)
    print(terminal(result), flush=True)
    if args.op != "status":
        path = export_random_summary(root / "assessment_reports" / stamp(), result)
        print(f"REPORT={path}\nSUMMARY_JSON={path.parent / 'summary.json'}", flush=True)
    return (
        130
        if interrupted
        else 0
        if result["complete"]
        or (args.op == "status" and result["status"] in {"READY", "INCOMPLETE"})
        else 2
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print("RANDOM_ASSESSMENT_STOPPED=" + clean(str(exc)), flush=True)
        raise SystemExit(2) from None
