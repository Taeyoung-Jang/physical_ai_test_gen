"""Read-only episode accounting and descriptive statistics for three paired repetitions."""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import checked_manifest
from failure_client.reporting.humanoid_assessment import checkpoint
from llm_afs.behavior import digest


def describe(repetitions):
    completed = [r for r in repetitions if r["complete"]]
    result = {
        "repetitions": repetitions,
        "complete_pairs": len(completed),
        "all_complete": len(completed) == 3,
        "statistical_superiority_established": False,
    }
    if len(completed) == 3:
        result["by_method"] = {}
        for method in ("afs", "random"):
            rates = [r["arms"][method]["fail"] / 7 for r in completed]
            result["by_method"][method] = {
                "valid": 21,
                "fail": sum(r["arms"][method]["fail"] for r in completed),
                "per_repetition_failure_rates": rates,
                "mean_failure_rate": statistics.mean(rates),
                "sample_std_failure_rate": statistics.stdev(rates),
            }
        differences = [
            (r["arms"]["afs"]["fail"] - r["arms"]["random"]["fail"]) / 7 for r in completed
        ]
        result["paired_difference_percentage_points"] = {
            "mean": statistics.mean(differences) * 100,
            "sample_std": statistics.stdev(differences) * 100,
        }
    result["limits"] = [
        "Development replication in previously selected fixed-base local domain",
        "One newly executed baseline is included in each arm's seven episodes",
        "Different search seeds, not exact replay of previously discovered scenes",
        "Only three complete pairs permit aggregate rate/variation here; no superiority test",
        "Goal PASS/FAIL and human safety are separate; safety is in per-campaign reports",
    ]
    return result


def report(root):
    root = Path(root).resolve()
    bundle = json.loads((root / "repetitions.json").read_text())
    if bundle["sha256"] != digest(bundle["value"]):
        raise ValueError("repetition plan changed")
    repetitions, evidence_ids = [], set()
    common_condition = None
    for planned in bundle["value"]["repetitions"]:
        directory = root / planned["directory"]
        wrapped = json.loads((directory / "manifest.json").read_text())
        m = checked_manifest(wrapped)
        if wrapped["sha256"] != planned["manifest_sha256"]:
            raise ValueError("frozen campaign changed")
        if (
            m["design"]["seeds"] != [planned["seed"]]
            or m["methods"] != ["afs", "random"]
            or m["design"]["valid_per_arm"] != 7
            or m["design"]["attempts_per_arm"] != 7
        ):
            raise ValueError("expected seven episodes per method for one repetition seed")
        condition = digest(
            {
                k: m[k]
                for k in (
                    "robot_config",
                    "reference_condition_id",
                    "domain_id",
                    "matched_local",
                    "environment",
                )
            }
        )
        if common_condition is not None and condition != common_condition:
            raise ValueError("repetition robot/domain conditions differ")
        common_condition = condition
        if checkpoint(directory)["manifest_sha256"] != wrapped["sha256"]:
            raise ValueError("parent checkpoint differs")
        arms = {}
        for method in ("afs", "random"):
            arm = directory / "seeds" / str(planned["seed"]) / method
            state = checkpoint(arm)
            lock = state["lock"]
            if (
                state["lock_sha256"] != digest(lock)
                or json.loads((arm / "protocol.json").read_text())
                != {"lock": lock, "lock_sha256": digest(lock)}
                or lock["plan"]["manifest_sha256"] != wrapped["sha256"]
                or lock["plan"]["target_config"] != m["robot_config"]
            ):
                raise ValueError("arm condition binding changed")
            valid, counts = [], Counter()
            for attempt in state["attempts"]:
                episode = attempt.get("episode")
                if episode is None:
                    continue
                if episode["status"] != "VALID":
                    continue
                archive = arm / "attempts" / attempt["id"] / "rollout"
                if Path(episode["source"]["path"]).resolve() != archive.resolve():
                    raise ValueError("episode archive outside own arm")
                for name in ("result.json", "protocol.json", "decisions.jsonl"):
                    if (
                        hashlib.sha256((archive / name).read_bytes()).hexdigest()
                        != episode["artifact_hashes"][name]
                    ):
                        raise ValueError("episode evidence changed")
                if (
                    json.loads((archive / "result.json").read_text())["task_outcome"]
                    != episode["task_outcome"]
                ):
                    raise ValueError("native verdict changed")
                if episode["evidence_id"] in evidence_ids:
                    raise ValueError("duplicate episode evidence")
                evidence_ids.add(episode["evidence_id"])
                valid.append(episode)
                counts[
                    sum(
                        v != m["matched_local"]["base_parameters"][k]
                        for k, v in attempt["candidate"]["parameters"].items()
                    )
                ] += 1
            pending = state["pending"] is not None
            arms[method] = {
                "status": state["status"],
                "attempted": len(state["attempts"]),
                "valid": len(valid),
                "pass": sum(r["task_outcome"] == "PASS" for r in valid),
                "fail": sum(r["task_outcome"] == "FAIL" for r in valid),
                "excluded": sum(
                    a.get("episode", {}).get("status") not in (None, "VALID")
                    for a in state["attempts"]
                ),
                "pending": pending,
                "changed_axis_counts": dict(counts),
                "complete": state["status"] == "COMPLETE"
                and len(valid) == 7
                and not pending
                and counts == {0: 1, 1: 3, 2: 3},
            }
        repetitions.append(
            {
                "seed": planned["seed"],
                "arms": arms,
                "complete": all(a["complete"] for a in arms.values()),
            }
        )
    result = describe(repetitions)
    atomic_json(root / "replication_summary.json", result)
    lines = ["=== 휴머노이드 AFS / Random 독립 3회 반복 ==="]
    for r in repetitions:
        row = f"seed {r['seed']}"
        for method, a in r["arms"].items():
            row += (
                f" | {method}: 유효 {a['valid']}/7, PASS {a['pass']}, "
                f"FAIL {a['fail']}, 제외 {a['excluded']}"
            )
        lines.append(row)
    lines.append(f"완료된 비교 세트: {result['complete_pairs']}/3")
    if result["all_complete"]:
        for method, d in result["by_method"].items():
            lines.append(
                f"{method} 실패 발견률 평균 {d['mean_failure_rate']:.1%}, "
                f"세트 간 표준편차 {d['sample_std_failure_rate']:.1%}"
            )
    lines.append("목표 판정과 사람 안전 측정은 별도입니다. 통계적 우위 확정은 아닙니다.")
    (root / "replication_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    print(f"SUMMARY={root / 'replication_summary.json'}", flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--require-all", action="store_true")
    args = p.parse_args()
    result = report(args.root)
    if args.require_all and not result["all_complete"]:
        raise SystemExit(2)
