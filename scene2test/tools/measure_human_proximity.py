"""Experimental reference measurement, NOT a fourth-family discovery or live run."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.human_proximity import measure_human_proximity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, help="new directory only")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args(argv)
    if args.stdout_only and args.output_dir:
        parser.error("--stdout-only cannot be combined with --output-dir")
    try:
        raw = args.input.read_bytes()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or set(data) != {"input_origin", "task_outcome", "contract", "samples"}
            or data["input_origin"] not in {"synthetic_fixture", "caller_declared"}
        ):
            raise ValueError("explicit synthetic/caller-declared input required")
        report = measure_human_proximity(
            data["contract"], data["samples"], task_outcome=data["task_outcome"]
        )
        report.update(
            input_origin=data["input_origin"], input_sha256=hashlib.sha256(raw).hexdigest()
        )
        body = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.stdout_only:
            print(body, end="")
            return 0
        root = args.output_dir or Path("/workspace/g1_failure/runtime/human_proximity") / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        )
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=False)
        (root / "input.json").write_bytes(raw)
        (root / "measurement.json").write_text(body, encoding="utf-8")
        files = ("input.json", "measurement.json")
        manifest = {
            "schema_version": "human-proximity-export-v1",
            "files": {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in files},
            "claim": "Declared-input measurement only, not a verified robot rollout",
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"Measurement stopped: {type(exc).__name__}: {exc}\n")
    print(f"MEASUREMENT={root / 'measurement.json'}")
    print(f"DIAGNOSTIC={report['diagnostic_status']}; unchanged_goal={report['task_outcome']}")
    print("No robot/API executed; experimental contract only; eligible_for_family_coverage=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
