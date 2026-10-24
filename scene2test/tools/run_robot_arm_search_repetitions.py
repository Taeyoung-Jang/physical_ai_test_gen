"""Three fresh independent paired search sets; preserve the original 12+12 design."""

import argparse
import copy
import fcntl
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import run_robot_arm_free_pair_search as cli  # noqa: E402

from robot_arm import free_pair_search as experiment  # noqa: E402
from robot_arm import placement, search  # noqa: E402

ROOT = PROJECT / "experiments/robot_arm_libero/free_pair_search_repetitions3_v1"
BASE = PROJECT / "config/robot_arm_free_pair_comparison.json"
VERSION = "three-independent-free-pair-search-sets-v1"
LAUNCHER = PROJECT / "tools/run_robot_arm_search_repetitions.sh"


def save_derived(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        name = stream.name
    os.replace(name, path)


def prepare(root, masters):
    """Offline only. Sample once before outcomes; never filter/resample by geometry."""
    import random

    if root.exists():
        raise FileExistsError("preserve prepared output; no reinitialization")
    if len(masters) != 3 or len(set(masters)) != 3:
        raise ValueError("three distinct master seeds required")
    base = experiment.validate(search.read(BASE))
    used = set(base["experiment"]["seeds"])
    designs = []
    for master in masters:
        rng = random.Random(master)
        seeds = rng.sample([s for s in range(80000, 99000) if s not in used], 3)
        used.update(seeds)
        design = copy.deepcopy(base)
        design["experiment"]["seeds"] = seeds
        designs.append(experiment.validate(design))
    sources = cli.sources(base["experiment"]) + [Path(__file__).resolve(), LAUNCHER, BASE]
    frozen = search.freeze(designs[0]["experiment"], sources)
    root.mkdir(parents=True, exist_ok=False)
    sets = []
    for number, (master, design) in enumerate(zip(masters, designs, strict=True), 1):
        child = root / f"set_{number}"
        child.mkdir()
        manifest = copy.deepcopy(frozen)
        manifest.update(config=design["experiment"], mode=experiment.VERSION, design=design)
        placement.save(child / "manifest.json", manifest)
        (child / "manifest.sha256").write_text(search.sha(child / "manifest.json") + "\n")
        placement.save(
            child / "plan.json",
            {
                "design": design,
                "robot_attempt_cap": 24,
                "afs_request_cap": 6,
                "planned_random": [
                    {
                        "seed": s,
                        "index": i,
                        "candidate": experiment.candidate(
                            design, experiment.uniform(design, s, i), s, i, "uniform"
                        ),
                    }
                    for s in design["experiment"]["seeds"]
                    for i in range(4)
                ],
                "executed": False,
            },
        )
        sets.append(
            {
                "set": number,
                "master_seed": master,
                "search_seeds": design["experiment"]["seeds"],
                "directory": child.name,
                "manifest_sha256": search.sha(child / "manifest.json"),
            }
        )
    plan = {
        "version": VERSION,
        "sets": sets,
        "robot_attempt_cap": 72,
        "afs_request_cap": 18,
        "control_step_cap": 21600,
        "sampling": (
            "Three SystemRandom master seeds drawn once; "
            "three new search seeds per master; no filtering"
        ),
        "history": "Each set/seed/arm starts empty; no old outcome import",
        "design": "Original 3 seeds x 4 slots/method; 2 bootstrap + 2 later slots/seed",
        "primary_metric": (
            "native FAIL / 12 allocated slots per method per complete set; "
            "exclusion is no discovery"
        ),
        "aggregation": "Mean and sample SD (ddof=1) across 3 complete sets, not pooled episodes",
        "scope": "Development-selected domain; not general superiority or causal families",
    }
    placement.save(root / "repetitions.json", plan)
    (root / "repetitions.sha256").write_text(search.sha(root / "repetitions.json") + "\n")
    return plan


def plan_for(root):
    if (root / "repetitions.sha256").read_text().strip() != search.sha(root / "repetitions.json"):
        raise ValueError("repetition plan changed")
    plan = search.read(root / "repetitions.json")
    if plan["version"] != VERSION or len(plan["sets"]) != 3:
        raise ValueError("wrong repetition contract")
    normalized = []
    used = set()
    for row in plan["sets"]:
        child = root / row["directory"]
        if search.sha(child / "manifest.json") != row["manifest_sha256"]:
            raise ValueError("child manifest changed")
        if (child / "manifest.sha256").read_text().strip() != row["manifest_sha256"]:
            raise ValueError("child manifest seal changed")
        m = search.read(child / "manifest.json")
        design = experiment.validate(m["design"])
        if m["config"] != design["experiment"]:
            raise ValueError("config/design mismatch")
        seeds = design["experiment"]["seeds"]
        if seeds != row["search_seeds"] or used.intersection(seeds):
            raise ValueError("seeds reused or inconsistent")
        used.update(seeds)
        d = copy.deepcopy(design)
        d["experiment"].pop("seeds")
        normalized.append(d)
    if any(d != normalized[0] for d in normalized[1:]):
        raise ValueError("sets have different conditions")
    return plan


def summarize(root):
    plan = plan_for(root)
    rows = []
    for row in plan["sets"]:
        s = experiment.summary(root / row["directory"])
        rows.append(
            {
                **row,
                "summary": s,
                "attempt_rates": {method: t["fail"] / 12 for method, t in s["totals"].items()},
            }
        )
    complete = all(row["summary"]["attempt_budget_complete"] for row in rows)
    aggregate = None
    if complete:
        aggregate = {}
        for method in ("afs", "random"):
            rates = [row["attempt_rates"][method] for row in rows]
            aggregate[method] = {
                "per_set_percent": [100 * x for x in rates],
                "mean_percent": 100 * statistics.mean(rates),
                "sample_sd_percentage_points": 100 * statistics.stdev(rates),
            }
        diffs = [100 * (r["attempt_rates"]["afs"] - r["attempt_rates"]["random"]) for r in rows]
        aggregate["paired_difference"] = {
            "per_set_percentage_points": diffs,
            "mean_percentage_points": statistics.mean(diffs),
            "sample_sd_percentage_points": statistics.stdev(diffs),
        }
    return {
        "complete": complete,
        "sets": rows,
        "aggregate": aggregate,
        "primary_denominator": "12 allocated slots per method in each complete set",
        "partial_rates_provisional": not complete,
        "statistical_superiority_established": False,
        "scope": plan["scope"],
        "caution": "Only 3 sets; geometric settings and motion patterns are not causal families.",
    }


def write_report(root):
    result = summarize(root)
    save_derived(root / "replication_summary.json", result)
    lines = ["로봇팔 독립 탐색 3세트", "세트 | AFS 실패/12 | Random 실패/12 | 완료"]
    for r in result["sets"]:
        t = r["summary"]["totals"]
        lines.append(
            f"{r['set']} | {t['afs']['fail']}/12 | {t['random']['fail']}/12 | "
            f"{r['summary']['attempt_budget_complete']}"
        )
        for method in ("afs", "random"):
            x = t[method]
            lines.append(
                f"  {method}: 시도{x['attempts']} 유효{x['valid']} 제외{x['excluded']} "
                f"pending{x['pending']} 고유실패{x['unique_failing_environment_settings']} "
                f"움직임분류={x['failure_motion_patterns']}"
            )
    if result["aggregate"]:
        for method in ("afs", "random"):
            a = result["aggregate"][method]
            lines.append(
                f"{method}: 평균 {a['mean_percent']:.2f}% ± 표본SD "
                f"{a['sample_sd_percentage_points']:.2f}%p"
            )
    else:
        lines.append("미완료: 평균·표준편차는 세 세트 완료 후 계산합니다.")
    lines.append(result["caution"])
    text = "\n".join(lines) + "\n"
    (root / "replication_summary.txt").write_text(text)
    print(text, flush=True)
    return result


def execute(root):
    plan = plan_for(root)
    # Read-only preflight all sets before any request. No credentials are printed.
    from robot_arm.openrouter import require_key

    require_key()
    for row in plan["sets"]:
        print(f"VERIFY set {row['set']}/3 source/model hashes", flush=True)
        experiment.verify(root / row["directory"])
    for row in plan["sets"]:
        child = root / row["directory"]
        print(
            f"독립 세트 {row['set']}/3: AFS12 + Random12; seeds={row['search_seeds']}", flush=True
        )
        try:
            child_process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(PROJECT / "tools/run_robot_arm_free_pair_search.py"),
                    "run",
                    "--live",
                    "--output",
                    str(child),
                    "--max-new-attempts",
                    "24",
                ],
                start_new_session=True,
            )
            try:
                code = child_process.wait()
            except KeyboardInterrupt:
                os.killpg(child_process.pid, signal.SIGINT)
                child_process.wait(timeout=30)
                raise
        except KeyboardInterrupt:
            write_report(root)
            raise
        result = write_report(root)
        if code:
            raise RuntimeError(
                f"set {row['set']} stopped (exit {code}); preserve evidence; no retry/replacement"
            )
    if not result["complete"]:
        raise RuntimeError("not all allocated budgets complete")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--status", action="store_true")
    a = p.parse_args()
    root = a.output.resolve()
    plan = plan_for(root)
    if a.status:
        write_report(root)
    elif not a.live:
        print(json.dumps(plan, indent=2))
        print("PREPARED only; --live starts 72 new robot episodes and up to 18 AFS requests.")
    else:
        with (root / ".run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            execute(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
