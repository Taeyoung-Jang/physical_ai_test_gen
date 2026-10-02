"""Inspect scene/rule coverage readiness locally. No API key, GPU or rollout needed."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.domain_readiness import SCHEMAS, audit_domain
from failure_client.reporting.domain_readiness_report import write_domain_audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", choices=SCHEMAS, default="clear-path-obstacles-v3")
    parser.add_argument("--output-dir", type=Path, help="new directory; never overwrites")
    parser.add_argument("--stdout-only", action="store_true", help="JSON only; no files created")
    args = parser.parse_args(argv)
    if args.stdout_only and args.output_dir:
        parser.error("--stdout-only cannot be combined with --output-dir")
    try:
        audit = audit_domain(args.schema)
        if args.stdout_only:
            print(json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        output = args.output_dir or Path("/workspace/g1_failure/runtime/failure_domain_audit") / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        )
        report = write_domain_audit(output, audit)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"Domain audit stopped: {type(exc).__name__}: {exc}\n")
    print(f"DOMAIN_AUDIT={report.parent}")
    print(f"REPORT={report}")
    print("READINESS=" + json.dumps(audit["target_readiness"]))
    print("No robot/API executed; no goal verdicts or observed family coverage assigned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
