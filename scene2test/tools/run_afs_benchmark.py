"""Explicitly initialize, execute, resume and inspect the local behavior-AFS pilot."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.research_campaign import ResearchCampaign
from failure_client.experiments.research_protocol import CampaignConfig
from robot_vlm.debug_log import clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    init = commands.add_parser("init", help="freeze config/code/assets; no API or robot launch")
    init.add_argument("--config", type=Path, required=True)
    init.add_argument("--output-dir", type=Path)
    for name in ("run", "status", "report", "resolve"):
        sub = commands.add_parser(name)
        sub.add_argument("--campaign", type=Path, required=True)
        if name == "run":
            sub.add_argument(
                "--live", action="store_true", help="explicitly permit paid API/GPU runs"
            )
            sub.add_argument(
                "--max-new-attempts", type=int, help="invocation limit; not a task budget"
            )
        elif name == "report":
            sub.add_argument("--with-memory", action="store_true")
        elif name == "resolve":
            sub.add_argument("--abandon-pending", required=True)
            sub.add_argument(
                "--note", required=True, help="confirm the operation is no longer active"
            )
    args = parser.parse_args(argv)
    if args.operation == "run" and (not args.live or not os.getenv("OPENAI_API_KEY")):
        parser.error("run requires --live and OPENAI_API_KEY in the local environment")
    try:
        if args.operation == "init":
            config = CampaignConfig.model_validate(read_json(args.config))
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
            root = args.output_dir or Path("/workspace/g1_failure/runtime/afs_benchmark") / stamp
            ResearchCampaign.create(root, config)
            print(f"AFS_CAMPAIGN={root.resolve()}")
            print(json.dumps(config.design(), indent=2, ensure_ascii=False))
            return
        campaign = ResearchCampaign(
            args.campaign,
            on_event=lambda event, detail: print(
                "CAMPAIGN_EVENT=" + event + " " + json.dumps(detail, ensure_ascii=False), flush=True
            ),
        )
        if args.operation == "run":
            campaign.run(max_new_attempts=args.max_new_attempts)
        elif args.operation == "resolve":
            campaign.abandon_pending(args.abandon_pending, args.note)
        elif args.operation == "report":
            print(f"REPORT={campaign.report(with_memory=args.with_memory)}")
        print(json.dumps(campaign.summary(), indent=2, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        parser.exit(
            2,
            f"Campaign stopped: {type(exc).__name__}: {clean(exc)}\n"
            "Inspect status / last_error.json. No automatic retry or Random fallback.\n",
        )


if __name__ == "__main__":
    main()
