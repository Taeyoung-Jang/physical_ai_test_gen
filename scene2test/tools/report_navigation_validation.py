"""Report every saved attempt; optionally verify remote artifacts by streaming hashes."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--data-root", type=Path, default=Path("/workspace/g1_failure/runtime/navigation_server")
    )
    parser.add_argument("--verify-url")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite report")
    headers = (
        {"Authorization": "Bearer " + os.environ["SIM_SERVER_API_KEY"]}
        if os.getenv("SIM_SERVER_API_KEY")
        else {}
    )
    rows, verified = [], 0
    lines = [
        "# G1 procedural navigation validation",
        "",
        "Known-map, ground-truth-pose static navigation; not LLM/VLA or sensor-based navigation.",
        "",
        "All attempts are listed. Regression cases do not estimate random-world success rates.",
        "",
        "| Stage | Navigator | Result | Sim s | Error (m) | Collision | Fall | Evidence |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    with httpx.Client(headers=headers, timeout=120) as client:
        for run in args.runs:
            for entry in json.loads((run / "summary.json").read_text()):
                stage = entry["stage"]
                result = json.loads((run / f"{stage}_result.json").read_text())
                facts = result["task_facts"]
                job = args.data_root / "outputs/jobs" / entry["job_id"]
                for artifact in result["artifacts"]:
                    if not args.verify_url:
                        continue
                    digest, length = hashlib.sha256(), 0
                    url = (
                        args.verify_url.rstrip("/") + "/api/v1/artifacts/" + artifact["artifact_id"]
                    )
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            digest.update(chunk)
                            length += len(chunk)
                    if (
                        digest.hexdigest() != artifact["sha256"].removeprefix("sha256:")
                        or length != artifact["size_bytes"]
                    ):
                        raise ValueError(f"artifact hash mismatch: {artifact['artifact_id']}")
                    verified += 1
                version = result["reproduction"].get("navigator", {}).get("id", "unknown")
                lines.append(
                    f"| {stage} | {version} | {result['execution']['termination_reason']} | "
                    f"{facts.get('elapsed_simulation_s', 0):.2f} | "
                    f"{facts.get('goal_distance_m', 0):.3f} | "
                    f"{facts.get('collision_observed')} | {facts.get('fall_observed')} | "
                    f"[MP4]({job / 'rollout.mp4'}) · [trajectory]({job / 'trajectory.png'}) |"
                )
                rows.append(
                    {
                        "stage": stage,
                        "job_id": entry["job_id"],
                        "navigator": version,
                        "execution": result["execution"],
                        "facts": facts,
                        "provider": result["reproduction"]
                        .get("runtime", {})
                        .get("execution_provider"),
                        "run": str(run),
                    }
                )
    lines += ["", f"Artifacts verified through HTTP: {verified}", "", "## Reproduction inputs", ""]
    lines += [f"- [{r.name}]({r})" for r in args.runs]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write("\n".join(lines) + "\n")
    json_path = args.output.with_suffix(".json")
    with json_path.open("x") as output:
        json.dump({"attempts": rows, "http_verified_artifacts": verified}, output, indent=2)
    print(json.dumps({"report": str(args.output), "attempts": len(rows), "verified": verified}))


if __name__ == "__main__":
    main()
