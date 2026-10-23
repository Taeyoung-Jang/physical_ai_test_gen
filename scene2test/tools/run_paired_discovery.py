"""Prepare and inspect latest trajectory AFS/Random comparison. Paid execution is opt-in."""

import argparse
import json
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.afs_autonomous import stamp
from failure_client.experiments.paired_discovery import PairedDesign, PairedDiscovery, paired_plan
from robot_vlm.debug_log import clean


def compact(value):
    return (
        {
            k: value[k]
            for k in (
                "campaign",
                "purpose",
                "status",
                "evaluation_complete",
                "new_attempts",
                "afs_requests_attempted",
                "robot_api_call_upper_bound",
                "afs_request_upper_bound",
            )
        }
        | (
            {
                "domain_id": value["domain_id"],
                "domain_scope": value["scene_domain"]["scope"],
                "domain_geometry_audit": value["domain_geometry_audit"],
            }
            if "scene_domain" in value
            else {}
        )
        | {
            "baseline_check": value.get("baseline_check", {"status": "not_required"}),
            "matched_change_counts": value.get("matched_change_counts", []),
            **(
                {
                    "dynamic_human_safety": {
                        "comparison_status": value["dynamic_human_safety"]["comparison_status"],
                        "relative_event_rate_gain": value["dynamic_human_safety"][
                            "relative_event_rate_gain"
                        ],
                        "arms": [
                            {
                                k: a[k]
                                for k in (
                                    "method",
                                    "seed",
                                    "valid",
                                    "measured",
                                    "unknown",
                                    "events",
                                    "event_rate",
                                    "goal_pass_with_event",
                                    "triggered_episodes",
                                )
                            }
                            for a in value["dynamic_human_safety"]["arms"]
                        ],
                    }
                }
                if "dynamic_human_safety" in value
                else {}
            ),
            "arms": [
                {
                    k: r[k]
                    for k in (
                        "method",
                        "seed",
                        "status",
                        "attempted",
                        "valid",
                        "pass",
                        "fail",
                        "excluded",
                        "afs_requests_attempted",
                    )
                }
                for r in value["arms"]
            ],
            "comparison": value["comparison"],
            "smoke_is_not_target_achievement": value["smoke_is_not_target_achievement"],
            "measured_families": {
                profile: {
                    method: group["discovered_families"]
                    for method, group in view["pooled_by_method"].items()
                }
                for profile, view in value["metrics"].items()
            },
            "failure_classification_counts": {
                method: group["counts"]
                for method, group in value["classification_explanations"]["system_twelve"][
                    "pooled_by_method"
                ].items()
            },
        }
    )


def main(argv=None, *, random_only=False):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="op", required=True)
    for op in ("plan", "init"):
        p = commands.add_parser(op, help="offline; no API/robot calls")
        p.add_argument("--config", type=Path, required=True)
        p.add_argument(
            "--run",
            type=Path,
            action="append",
            required=True,
            help="verified controls bind settings only, not evaluation history",
        )
        if op == "init":
            p.add_argument("--output-dir", type=Path)
    for op in ("run", "status", "report"):
        p = commands.add_parser(op)
        p.add_argument("--campaign", type=Path, required=True)
        if op == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-new-attempts", type=int, default=1)
            p.add_argument("--max-new-afs-requests", type=int, default=1)
            p.add_argument("--continue-after-exclusion", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.op in {"plan", "init"}:
            design = PairedDesign.model_validate(read_json(args.config))
            if random_only and design.purpose != "random-environment-sweep":
                raise ValueError("Random-only entry point requires a Random sweep design")
            wrapped = paired_plan(args.run, design)
            m = wrapped["manifest"]
            print(
                "PLAN="
                + json.dumps(
                    {
                        k: m[k]
                        for k in (
                            "design",
                            "robot_config",
                            "valid_total",
                            "attempt_cap_total",
                            "robot_api_call_upper_bound",
                            "afs_request_upper_bound",
                            "external_history_in_evaluation",
                            "bootstrap",
                            "random_distribution",
                        )
                    },
                    ensure_ascii=False,
                )
            )
            if design.scene_domain is not None:
                print("SHARED_DOMAIN=" + json.dumps(design.scene_domain, ensure_ascii=False))
            if args.op == "init":
                root = (
                    args.output_dir
                    or Path("/workspace/g1_failure/runtime/paired_discovery") / stamp()
                )
                PairedDiscovery.create(root, wrapped)
                print(f"CAMPAIGN={root.resolve()}; no API or robot launched", flush=True)
            return 0
        campaign = PairedDiscovery(
            args.campaign,
            on_event=lambda event: print(
                "PAIRED_EVENT=" + json.dumps(event, ensure_ascii=False), flush=True
            ),
        )
        if random_only and campaign.design.methods != ["random"]:
            raise ValueError("Random-only entry point refuses paired/AFS campaigns")
        if args.op == "run":
            campaign.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                max_new_afs_requests=args.max_new_afs_requests,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        if args.op in {"run", "report"}:
            report = campaign.report()
            print(f"REPORT={report}", flush=True)
            # Print the exact saved snapshot; do not reparse every large trace again.
            result = read_json(report.parent / "summary.json")
        else:
            result = campaign.summary()
        print("SUMMARY=" + json.dumps(compact(result), ensure_ascii=False), flush=True)
        return 2 if result["status"] not in {"READY", "COMPLETE"} else 0
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}; no automatic retry", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
