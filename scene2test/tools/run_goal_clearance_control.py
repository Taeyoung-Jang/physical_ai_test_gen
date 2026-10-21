"""Validate one predeclared goal-clearance control; never launch the final comparison."""

import argparse
import json
from pathlib import Path

from clear_path.fixture import box_start
from clear_path.scene_space import axes_for_schema
from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.experiments.afs_contrast import PROBE_DESIGN, probe_validation_plan
from failure_client.experiments.behavior_regression import BehaviorRegression
from failure_client.experiments.local_goal_adapter import LocalGoalRunner, atomic_json
from failure_client.experiments.research_protocol import PROJECT, CampaignConfig
from robot_vlm.debug_log import clean
from robot_vlm.navigation_tools import plan as navigation_plan
from robot_vlm.policy import Observation

ROOT = Path("/workspace/g1_failure/runtime/goal_clearance_control/luna_clear_goal_20261021_v1")
BASE = Path("/workspace/g1_failure/runtime/factor_calibration/luna_oat_20261021_v1")


def prepare_plan(paths):
    plan = probe_validation_plan(paths, axis="box_lateral_fraction", value=1.0, repeats=2)
    case = plan["cases"][0]
    cfg = CampaignConfig.model_validate(case["target_config"])
    xy = box_start(cfg.scene({k: case["scene"][k] for k in axes_for_schema(cfg.scene_schema)}))
    source_hash = _hash_file(PROJECT / "src/robot_vlm/navigation_tools.py")
    checks = []
    for record, protocol in zip(case["baselines"], case["baseline_protocols"], strict=True):
        if protocol["source_hashes"].get("navigation_tools") != source_hash:
            raise ValueError("archived planner differs from current planner")
        path = Path(record["source"]["path"]) / "observation_000.json"
        if _hash_file(path) != record["artifact_hashes"].get(path.name):
            raise ValueError("saved observation changed")
        observation = Observation.model_validate(read_json(path))
        boxes = [g for g in observation.geometry if g.object_id == "clear_box_geom"]
        if len(boxes) != 1:
            raise ValueError("one observed box required")
        # In-memory geometric diagnostic only: no simulator, source rewrite or verdict.
        boxes[0].center_m[:2] = xy
        result = navigation_plan(observation, case["task_contract"]["goal"]["target_xy_m"])
        if result["status"] != "path_found":
            raise ValueError("candidate has no initial static planner route")
        checks.append({"evidence_id": record["evidence_id"], "planner_status": result["status"]})
    plan["control_readiness"] = {
        "geometry_checks": checks,
        "planner_source_sha256": source_hash,
        "claim": "Static connectivity only, not a measured PASS or physical feasibility proof",
        "next_step": "Inspect both repeats before separately freezing any AFS/Random evaluation",
    }
    return plan


def logged_runner(cfg, directory, params):
    print("CONTROL_START=" + directory.name, flush=True)
    receipt = LocalGoalRunner()(cfg, directory, params)
    print("CONTROL_COLLECT=" + directory.name, flush=True)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("init", "run", "status", "report"):
        p = sub.add_parser(op)
        p.add_argument("--suite", type=Path, default=ROOT)
        if op == "init":
            p.add_argument("--run", type=Path, action="append")
        if op == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--continue-after-exclusion", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.op == "init":
            paths = args.run or [BASE / "attempts" / f"attempt_{i:05d}" / "rollout" for i in (0, 1)]
            plan = prepare_plan(paths)
            BehaviorRegression.create(args.suite, plan)
            atomic_json(args.suite / "control_plan.json", plan)
        engine = BehaviorRegression(args.suite, runner=logged_runner)
        plan = engine.state["lock"]["plan"]
        if plan.get("design") != PROBE_DESIGN or "control_readiness" not in plan:
            raise ValueError("not a prepared goal-clearance control suite")
        if args.op == "run":
            print("CONTROL_BUDGET=2 episodes / at most 20 robot calls / 0 AFS", flush=True)
            engine.run(
                live=args.live,
                max_new_attempts=2,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        report = engine.report()
        summary = read_json(report.parent / "summary.json")
        print(f"REPORT={report}")
        print("SUMMARY=" + json.dumps(summary, ensure_ascii=False))
        print("NEXT=Inspect results; no final comparison was launched automatically.")
        return 2 if summary["status"] == "NEEDS_ATTENTION" else 0
    except Exception as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}")
        if engine is not None:
            print(f"EVIDENCE={args.suite}; saved intents are preserved; no automatic retry")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
