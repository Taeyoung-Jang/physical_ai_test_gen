"""One-command AFS/Random pilot: plan, initialize/resume, execute, then report.

Without --live this only prints a plan. It never launches a mock/real robot implicitly.
"""

import argparse
import json
import os
import shlex
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.research_campaign import ResearchCampaign
from failure_client.experiments.research_protocol import PROJECT, CampaignConfig
from robot_vlm.debug_log import clean, exception_detail


def stamp():
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def checked_run(campaign, limit):
    """A goal FAIL is valid research data; an execution error stops the wrapper."""
    before = len(campaign.records())
    summary = campaign.run(max_new_attempts=limit)
    observed = campaign.records()[before:]
    if summary["status"] not in {"READY", "COMPLETE"}:
        raise RuntimeError(f"campaign stopped: {summary['status']}; reason={summary['reason']}")
    if summary["reason"] == "external_interruption":
        raise RuntimeError("external interruption; inspect the attempt before explicit resume")
    if any(record.status != "VALID" for record in observed):
        raise RuntimeError("excluded/incomplete rollout; inspect evidence before explicit resume")
    if limit and not observed and summary["status"] != "COMPLETE":
        raise RuntimeError("no observed progress; no automatic retry")
    return summary


def execute(campaign):
    """Reuse the existing locked runner; never resolve, resend or change its frozen config."""
    journal = campaign.root / "pilot_runs" / stamp()
    journal.mkdir(parents=True, exist_ok=False)
    print(f"PILOT_LOGS={journal}", flush=True)
    previous_callback = campaign.on_event

    def event(name, detail):
        row = {"utc": datetime.now(UTC).isoformat(), "event": name, "detail": detail}
        # Campaign events contain IDs/status, not policy inputs or credentials.
        line = json.dumps(row, ensure_ascii=False)
        with (journal / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
        print("CAMPAIGN_EVENT=" + clean(line), flush=True)
        if previous_callback is not None:
            previous_callback(name, detail)

    campaign.on_event = event
    exit_code = 0
    try:
        # Collect a pending archive/validate an existing response before any new launch.
        # Ambiguous calls are rejected by the campaign, never automatically resent.
        summary = checked_run(campaign, 0)
        for _ in range(2):
            if summary["status"] == "COMPLETE":
                break
            summary = checked_run(campaign, 1)
        atomic_json(journal / "initial_check.json", summary)
        initial_report = campaign.report(with_memory=True)
        print(f"INITIAL_REPORT={initial_report}", flush=True)
        print("INITIAL_CHECK=passed; continuing within the same frozen budget", flush=True)
        while summary["status"] != "COMPLETE":
            summary = checked_run(campaign, 1)
    except (Exception, KeyboardInterrupt) as exc:
        exit_code = 130 if isinstance(exc, KeyboardInterrupt) else 2
        atomic_json(journal / "error.json", {"exception_chain": exception_detail(exc)})
        print("PILOT_STOPPED=" + clean(exc), flush=True)
    finally:
        campaign.on_event = previous_callback
        # Reporting is read-only with respect to original rollouts and does not call a model.
        # Preserve the original nonzero exit even when a partial report succeeds.
        try:
            report = campaign.report(with_memory=True)
            print(f"REPORT={report}", flush=True)
        except (Exception, KeyboardInterrupt) as exc:
            exit_code = exit_code or (130 if isinstance(exc, KeyboardInterrupt) else 2)
            atomic_json(journal / "report_error.json", {"exception_chain": exception_detail(exc)})
            print("REPORT_ERROR=" + clean(exc), flush=True)
        summary = campaign.summary()
        atomic_json(journal / "summary.json", {"exit_code": exit_code, **summary})
        print("PILOT_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)
        print(f"PILOT_EXIT_CODE={exit_code}", flush=True)
        if exit_code:
            print(
                "RESUME_AFTER_INSPECTION=uv run --no-sync python tools/run_afs_pilot.py "
                "--live --campaign " + shlex.quote(str(campaign.root)),
                flush=True,
            )
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="allow the full paid API/GPU pilot")
    parser.add_argument("--config", type=Path, help="new campaign config; default: project example")
    paths = parser.add_mutually_exclusive_group()
    paths.add_argument("--campaign", type=Path, help="resume this existing campaign; never re-init")
    paths.add_argument("--output-dir", type=Path, help="exact NEW campaign directory")
    args = parser.parse_args(argv)
    if args.campaign and args.config:
        parser.error("--campaign uses its frozen config; do not also pass --config")
    if args.live and not os.getenv("OPENAI_API_KEY", "").strip():
        parser.error(
            "--live requires OPENAI_API_KEY in the local environment; never pass it as an argument"
        )
    try:
        if args.campaign:
            config = CampaignConfig.model_validate(
                read_json(args.campaign / "protocol.json")["lock"]["config"]
            )
        else:
            config = CampaignConfig.model_validate(
                read_json(args.config or PROJECT / "config/behavior_afs_benchmark.json")
            )
        print(
            "PILOT_PLAN="
            + json.dumps(
                {
                    "mode": "resume" if args.campaign else "new",
                    "seeds": config.seeds,
                    "valid_rollouts_per_method_seed": config.valid_budget_per_seed,
                    "valid_rollouts_total": 2 * len(config.seeds) * config.valid_budget_per_seed,
                    "max_attempts_total": 2 * len(config.seeds) * config.max_attempts_per_arm,
                    "robot_model": config.robot.model,
                    "afs_model": config.afs_model,
                    "scene_schema": config.scene_schema,
                    "max_simulation_s": config.robot.max_seconds,
                    "http_read_timeout_s": config.robot.response_timeout,
                    "watchdog_wall_s": config.robot.watchdog_wall_s,
                    "budget_scope": "whole campaign, including completed attempts on resume",
                    **config.design(),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not args.live:
            print("PLAN_ONLY: no files, API calls or robot launches; add --live to execute.")
            return 0
        root = (
            args.campaign
            or args.output_dir
            or (Path("/workspace/g1_failure/runtime/afs_benchmark") / stamp())
        )
        if args.campaign is None:
            ResearchCampaign.create(root, config)
        print(f"AFS_CAMPAIGN={root.resolve()}", flush=True)
        return execute(ResearchCampaign(root))
    except (Exception, KeyboardInterrupt) as exc:
        print("PILOT_ERROR=" + clean(exc), flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2


if __name__ == "__main__":
    raise SystemExit(main())
