"""Versioned goal regression, not an AFS arm or a deterministic reproduction claim.

Read-only planning; explicit bounded live execution with durable intent. Baseline
archives and outcomes are never rewritten. No retry or replacement of exclusions.
"""

import json
import os
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from clear_path.scene_space import axes_for_schema
from failure_client.archive.regression_cases import _scene_parameters, build_failure_memory
from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.failure_taxonomy import classify_record
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import EpisodeRecord, RunInput
from failure_client.storage.research_store import ResearchStore
from robot_vlm.task_outcome import digest, task_contract

from .local_goal_adapter import LocalGoalRunner, atomic_json
from .research_protocol import PROJECT, CampaignConfig, RobotSettings, environment_fingerprint


def replay_plan(paths, *, repeats=2, model=None, groot_root=None):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1..10; exclusions consume attempts")
    if not paths or len(paths) > 32:
        raise ValueError("select 1..32 baseline archives")
    records = [read_goal_run(RunInput(path=str(Path(p).resolve()))) for p in paths]
    if any(r.status != "VALID" for r in records):
        raise ValueError("only verified goal_outcome_v1 PASS/FAIL baselines are replayable")
    memory = build_failure_memory(records)
    cases = []
    for case in memory["cases"]:
        if case["parameters"] is None:
            raise ValueError("baseline geometry is not supported/reproducible")
        baselines = [memory["episodes"][eid]["record"] for eid in case["episodes"]]
        protocols = [read_json(Path(r["source"]["path"]) / "protocol.json") for r in baselines]
        protocol = protocols[0]
        robot = RobotSettings(
            model=model or protocol["model"],
            max_calls=protocol["max_calls"],
            max_seconds=protocol["max_simulation_s"],
            response_timeout=float(protocol["http_read_timeout_s"]),
            enable_push=protocol["push_enabled"],
            **({"groot_root": str(Path(groot_root).resolve())} if groot_root else {}),
        )
        if case["task_contract"] != task_contract([7.0, 0.0], robot.max_calls, robot.max_seconds):
            raise ValueError("baseline task contract is not supported by the current runner")
        config = CampaignConfig(scene_schema=case["parameters"]["schema_version"], robot=robot)
        cases.append(
            {
                "case_id": case["case_id"],
                "baseline_role": case["role"],
                "baseline_pass": case["pass_count"],
                "baseline_fail": case["fail_count"],
                "scene": case["parameters"],
                "geometry_id": case["geometry_id"],
                "task_contract": case["task_contract"],
                "baselines": baselines,
                "baseline_protocols": protocols,
                "target_config": config.model_dump(),
            }
        )
    return {
        "schema_version": "behavior-regression-plan-v1",
        "mode": "versioned_replay",
        "cases": cases,
        "attempts_per_case": repeats,
        "max_attempts": len(cases) * repeats,
        "robot_api_call_upper_bound": sum(
            c["target_config"]["robot"]["max_calls"] * repeats for c in cases
        ),
        "afs_requests": 0,
        "duplicates_excluded": memory["duplicates"],
        "limits": [
            "Goal, scene, task budget, push availability and timeout are fixed per baseline",
            "Current code is a versioned comparison, not exact old-code replay; "
            "model override is explicit",
            "Remote model/physics repeats need not be deterministic; "
            "changes are observations, not significance",
            "Excluded attempts consume budget; no replacement or automatic paid retry",
            "Baseline archives/external robot assets must remain accessible; MP4 only, no GIF",
        ],
    }


def memory_paths(path):
    """Memory export is an index, not authority to relabel or execute arbitrary commands."""
    value = read_json(Path(path))
    if value.get("schema_version") != "failure-memory-v1":
        raise ValueError("expected failure-memory-v1 memory.json")
    paths = []
    for entry in value["episodes"].values():
        saved = EpisodeRecord.model_validate(entry["record"])
        actual = read_goal_run(saved.source)
        if (
            actual.status != "VALID"
            or actual.evidence_id != saved.evidence_id
            or actual.artifact_hashes != saved.artifact_hashes
        ):
            raise ValueError("memory source missing or changed")
        paths.append(actual.source.path)
    return paths


def regression_fingerprint(config):
    value = environment_fingerprint(config)
    value["source_hashes"]["tools/run_behavior_regression.py"] = _hash_file(
        PROJECT / "tools/run_behavior_regression.py"
    )
    return value


def _verify_baselines(plan):
    for case in plan["cases"]:
        for row in case["baselines"]:
            verify_episode_files(EpisodeRecord.model_validate(row))


class BehaviorRegression:
    def __init__(self, root, *, runner=None, fingerprint=None):
        self.root = Path(root).resolve()
        if not (self.root / "campaign.sqlite3").is_file():
            raise ValueError("initialize a regression suite first")
        self.store = ResearchStore(self.root)
        self.runner = runner or LocalGoalRunner()
        self.fingerprint = fingerprint or regression_fingerprint
        self.state, self.revision = self.store.load()
        self._verify_lock()

    @classmethod
    def create(cls, root, plan, *, fingerprint=None, execution_origin="openai_api"):
        if plan.get("schema_version") != "behavior-regression-plan-v1":
            raise ValueError("invalid regression plan")
        fingerprint = fingerprint or regression_fingerprint
        _verify_baselines(plan)
        environments = {}
        for case in plan["cases"]:
            cfg = CampaignConfig.model_validate(case["target_config"])
            env = fingerprint(cfg)
            environments[case["case_id"]] = env
            for record, protocol in zip(case["baselines"], case["baseline_protocols"]):
                if record["policy_origin"] != execution_origin:
                    raise ValueError("mock and live baseline origins cannot be mixed")
                if any(
                    env["robot_resources"].get(k) != v
                    for k, v in protocol["robot_resources"].items()
                ):
                    raise ValueError("baseline robot resources changed or unavailable")
        root = Path(root).resolve()
        for case in plan["cases"]:
            for row in case["baselines"]:
                source = Path(row["source"]["path"]).resolve()
                if root.is_relative_to(source) or source.is_relative_to(root):
                    raise ValueError("output must be separate from all source archives")
        lock = {"plan": plan, "environments": environments, "execution_origin": execution_origin}
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
        state = {
            "schema_version": "behavior-regression-state-v1",
            "lock": lock,
            "lock_sha256": digest(lock),
            "status": "READY",
            "pending": None,
            "attempts": [],
            "target_conditions": {},
            "exclusion_acknowledgements": [],
        }
        ResearchStore(root).save(state, -1, "created")
        return root

    def _verify_lock(self):
        if self.state.get("schema_version") != "behavior-regression-state-v1":
            raise ValueError("not a regression suite")
        expected = {"lock": self.state["lock"], "lock_sha256": digest(self.state["lock"])}
        if (
            self.state["lock_sha256"] != expected["lock_sha256"]
            or read_json(self.root / "protocol.json") != expected
        ):
            raise ValueError("frozen regression protocol changed")

    def _save(self, event, detail=None):
        self.revision = self.store.save(self.state, self.revision, event, detail)

    def _fresh(self):
        self._verify_lock()
        _verify_baselines(self.state["lock"]["plan"])
        for case in self.state["lock"]["plan"]["cases"]:
            cfg = CampaignConfig.model_validate(case["target_config"])
            if self.fingerprint(cfg) != self.state["lock"]["environments"][case["case_id"]]:
                raise RuntimeError(
                    "frozen code/resources/dependencies changed; initialize a new suite"
                )
        for attempt in self.state["attempts"]:
            if attempt.get("episode", {}).get("status") == "VALID":
                verify_episode_files(EpisodeRecord.model_validate(attempt["episode"]))

    def _case(self, attempt):
        return next(
            c for c in self.state["lock"]["plan"]["cases"] if c["case_id"] == attempt["case_id"]
        )

    def _directory(self, attempt):
        return self.root / "attempts" / attempt["id"]

    def _ensure_not_running(self, directory):
        if (directory / "receipt.json").exists():
            return
        if (directory / "process.json").exists():
            pid = read_json(directory / "process.json")["pid"]
            if type(pid) is not int or pid <= 0:
                raise ValueError("invalid saved process id")
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            raise RuntimeError("saved process may still be active; no resend or collection")

    def _observe(self, attempt):
        directory = self._directory(attempt)
        self._ensure_not_running(directory)
        receipt = (
            read_json(directory / "receipt.json") if (directory / "receipt.json").exists() else None
        )
        record = read_goal_run(RunInput(path=str(directory / "rollout"), stage="repeat"))
        if receipt is None and record.status not in {"VALID", "INCONCLUSIVE"}:
            raise RuntimeError(
                "ambiguous pending attempt; inspect then explicitly exclude, never resend"
            )
        case = self._case(attempt)
        cfg = CampaignConfig.model_validate(case["target_config"])
        error = "external_interrupt" if receipt and receipt.get("interrupted") else None
        comparison = {}
        if record.status == "VALID" and not error:
            p = read_json(directory / "rollout/protocol.json")
            params, geometry, _ = _scene_parameters(directory / "rollout", p)
            expected = {
                "scene_config": case["scene"],
                "task_contract": case["task_contract"],
                "model": cfg.robot.model,
                "max_calls": cfg.robot.max_calls,
                "max_simulation_s": cfg.robot.max_seconds,
                "push_enabled": cfg.robot.enable_push,
                "http_read_timeout_s": cfg.robot.response_timeout,
                "policy_origin": self.state["lock"]["execution_origin"],
            }
            if (
                any(p.get(k) != v for k, v in expected.items())
                or params != case["scene"]
                or geometry != case["geometry_id"]
            ):
                error = "replay_contract_or_geometry_mismatch"
            elif any(
                record.evidence_id == a.get("episode", {}).get("evidence_id")
                for a in self.state["attempts"]
            ):
                error = "duplicate_core_evidence"
            elif any(record.evidence_id == r["evidence_id"] for r in case["baselines"]):
                error = "baseline_copy_is_not_a_replay"
            else:
                previous = self.state["target_conditions"].setdefault(
                    case["case_id"], record.condition_id
                )
                if record.condition_id != previous:
                    error = "target_condition_or_returned_model_drift"
            before = case["baseline_protocols"][0]
            comparison = {
                k: {"baseline": before.get(k), "current": p.get(k)}
                for k in sorted(before.keys() | p.keys())
                if before.get(k) != p.get(k)
            }
            baseline_models = case["baselines"][0]["returned_models"]
            if baseline_models != record.returned_models:
                comparison["returned_models"] = {
                    "baseline": baseline_models,
                    "current": record.returned_models,
                }
        attempt["raw_episode"] = record.model_dump()
        if error:
            record = EpisodeRecord.model_validate(
                {
                    **record.model_dump(),
                    "status": "INCONCLUSIVE",
                    "task_outcome": "INCONCLUSIVE",
                    "exclusion_reason": error,
                    "attribution": None,
                }
            )
        if record.status == "VALID":
            record = classify_record(record)
        attempt.update(
            episode=record.model_dump(), receipt=receipt, protocol_differences=comparison
        )
        self.state["pending"] = None
        self.state["status"] = "READY" if record.status == "VALID" else "NEEDS_ATTENTION"
        self._save(
            "observed",
            {"id": attempt["id"], "status": record.status, "outcome": record.task_outcome},
        )

    def run(self, *, live=False, max_new_attempts=None, continue_after_exclusion=False):
        if not live:
            raise ValueError("execution requires explicit live=True")
        if self.state["lock"]["execution_origin"] == "openai_api" and not os.getenv(
            "OPENAI_API_KEY"
        ):
            raise ValueError("OPENAI_API_KEY is required in the local environment")
        if max_new_attempts is not None and (
            type(max_new_attempts) is not int or max_new_attempts < 0
        ):
            raise ValueError("max_new_attempts must be nonnegative")
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._fresh()
            if self.state["pending"] is not None:
                self._observe(self.state["attempts"][self.state["pending"]])
            if self.state["status"] == "NEEDS_ATTENTION":
                if not continue_after_exclusion:
                    return self.summary()
                self.state["exclusion_acknowledgements"].append(len(self.state["attempts"]))
                self.state["status"] = "READY"
                self._save("operator_continues_after_exclusion")
            plan = self.state["lock"]["plan"]
            launched = 0
            while len(self.state["attempts"]) < plan["max_attempts"]:
                if max_new_attempts is not None and launched >= max_new_attempts:
                    break
                self._fresh()
                index = len(self.state["attempts"])
                case = plan["cases"][index // plan["attempts_per_case"]]
                attempt = {
                    "id": f"attempt_{index:05d}",
                    "case_id": case["case_id"],
                    "repeat_index": index % plan["attempts_per_case"],
                }
                self.state["attempts"].append(attempt)
                self.state["pending"] = index
                self._save("rollout_intent", attempt)
                cfg = CampaignConfig.model_validate(case["target_config"])
                params = {k: case["scene"][k] for k in axes_for_schema(cfg.scene_schema)}
                # Any exception retains the intent. Resumption only collects saved evidence.
                self.runner(cfg, self._directory(attempt), params)
                launched += 1
                self._fresh()
                self._observe(attempt)
                if self.state["status"] == "NEEDS_ATTENTION":
                    break
            if (
                len(self.state["attempts"]) == plan["max_attempts"]
                and self.state["pending"] is None
                and self.state["status"] == "READY"
            ):
                self.state["status"] = (
                    "COMPLETE_WITH_EXCLUSIONS"
                    if any(a["episode"]["status"] != "VALID" for a in self.state["attempts"])
                    else "COMPLETE"
                )
                self._save("fixed_attempt_budget_complete")
            return self.summary()

    def exclude_pending(self, *, note):
        if not isinstance(note, str) or not note.strip():
            raise ValueError("inspection note required")
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            index = self.state["pending"]
            if index is None:
                raise ValueError("no pending attempt")
            attempt = self.state["attempts"][index]
            directory = self._directory(attempt)
            self._ensure_not_running(directory)
            record = read_goal_run(RunInput(path=str(directory / "rollout"), stage="repeat"))
            if record.status in {"VALID", "INCONCLUSIVE"}:
                raise ValueError("saved evidence must be collected with run, not discarded")
            attempt.update(episode=record.model_dump(), operator_note=note)
            self.state.update(pending=None, status="NEEDS_ATTENTION")
            self._save("operator_excluded_ambiguous_attempt", {"id": attempt["id"], "note": note})

    def summary(self):
        plan = self.state["lock"]["plan"]
        rows = []
        for case in plan["cases"]:
            attempts = [a for a in self.state["attempts"] if a["case_id"] == case["case_id"]]
            records = [a["episode"] for a in attempts if "episode" in a]
            passed = sum(r["task_outcome"] == "PASS" for r in records)
            failed = sum(r["task_outcome"] == "FAIL" for r in records)
            excluded = sum(r["status"] != "VALID" for r in records)
            complete = len(records) == plan["attempts_per_case"]
            label = (
                "PENDING"
                if not complete
                else "INCONCLUSIVE"
                if excluded
                else (
                    "MIXED"
                    if (passed and failed) or (case["baseline_pass"] and case["baseline_fail"])
                    else "OBSERVED_REGRESSION"
                    if case["baseline_pass"] and failed
                    else "OBSERVED_IMPROVEMENT"
                    if case["baseline_fail"] and passed
                    else "RETAINED_PASS"
                    if passed
                    else "RETAINED_FAIL"
                )
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "baseline_role": case["baseline_role"],
                    "baseline_pass": case["baseline_pass"],
                    "baseline_fail": case["baseline_fail"],
                    "pass": passed,
                    "fail": failed,
                    "excluded": excluded,
                    "attempted": len(attempts),
                    "planned": plan["attempts_per_case"],
                    "comparison": label,
                }
            )
        records = [a["episode"] for a in self.state["attempts"] if "episode" in a]
        costs = {}
        for field in ("observed_input_tokens", "observed_output_tokens", "robot_api_calls"):
            values = [r[field] for r in records if r.get(field) is not None]
            costs[field] = {
                "observed": sum(values) if values else None,
                "missing_attempts": len(self.state["attempts"]) - len(values),
            }
        audits = [r["usage_audit"] for r in records if r.get("usage_audit")]
        costs["calls_missing_usage_observed"] = (
            sum(a["calls_missing_usage"] for a in audits) if audits else None
        )
        costs["attempts_without_usage_audit"] = len(self.state["attempts"]) - len(audits)
        return {
            "suite": str(self.root),
            "status": self.state["status"],
            "pending": self.state["pending"],
            "max_attempts": plan["max_attempts"],
            "robot_api_call_upper_bound": plan["robot_api_call_upper_bound"],
            "cases": rows,
            "new_execution_costs": costs,
            "limits": plan["limits"],
        }

    def report(self):
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            _verify_baselines(self.state["lock"]["plan"])
            for attempt in self.state["attempts"]:
                if attempt.get("episode", {}).get("status") == "VALID":
                    verify_episode_files(EpisodeRecord.model_validate(attempt["episode"]))
            output = self.root / "reports" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
            output.mkdir(parents=True, exist_ok=False)
            summary = self.summary()
            atomic_json(output / "summary.json", summary)
            atomic_json(output / "attempts.json", self.state["attempts"])
            links = []
            for a in self.state["attempts"]:
                video = self._directory(a) / "rollout/rollout.mp4"
                if video.is_file():
                    links.append(
                        f"<li>{escape(a['id'])}: "
                        f'<a href="../../attempts/{a["id"]}/rollout/rollout.mp4">MP4</a></li>'
                    )
            page = (
                '<!doctype html><meta charset="utf-8"><title>Behavior regression</title>'
                "<h1>버전별 목표 회귀 결과</h1>"
            )
            page += (
                "<p>반복 관측이며 통계적 성능 개선/퇴행의 확정은 아닙니다. "
                "원본 평가와 AFS 예산은 변경하지 않습니다.</p>"
            )
            page += (
                "<pre>"
                + escape(json.dumps(summary, indent=2, ensure_ascii=False))
                + "</pre><ul>"
                + "".join(links)
                + "</ul>"
            )
            page += (
                '<p><a href="attempts.json">실행 근거·유형·원본 대비 프로토콜 차이</a> · '
                '<a href="summary.json">요약 JSON</a></p>'
            )
            (output / "report.html").write_text(page, encoding="utf-8")
            atomic_json(
                output / "manifest.json",
                {
                    "artifacts": [
                        {"path": p.name, "sha256": _hash_file(p)} for p in sorted(output.iterdir())
                    ]
                },
            )
            return output / "report.html"
