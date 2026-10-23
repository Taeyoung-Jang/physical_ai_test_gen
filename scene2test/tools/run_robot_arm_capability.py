"""Prepare/run explicit boundary and static-obstacle probes with the public robot policy fixed."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import run_robot_arm_search as legacy_cli  # noqa: E402
from watch_robot_arm_search import Observer, display, stop_group  # noqa: E402

from robot_arm import capability, obstacles, placement, search  # noqa: E402

DEFAULT = PROJECT / "config/robot_arm_capability_suite.json"
ROOT = PROJECT / "experiments/robot_arm_libero/capability_suite_v1"


def suite_sources(c):
    return legacy_cli.sources(c) + [
        Path(__file__).resolve(),
        PROJECT / "src/robot_arm/obstacles.py",
        PROJECT / "src/robot_arm/capability.py",
    ]


def check_evidence(directory):
    manifest = search.read(directory / "evidence_manifest.json")
    for relative, expected in manifest.items():
        if search.sha(directory / relative) != expected:
            raise ValueError("case evidence changed: " + relative)


def worker(root, index):
    c = search.verify(root)
    suite = capability.validate_suite(search.read(root / "manifest.json")["suite"])
    case = suite["cases"][index]
    directory = root / f"attempt_{index:05d}"
    if search.read(directory / "robot_intent.json") != case:
        raise ValueError("case intent mismatch")
    placement.save(directory / "worker_started.json", {"pid": os.getpid()})
    try:
        result = obstacles.run(c, case, directory)
    except Exception:
        import traceback

        traceback.print_exc()
        result = {
            "status": "INCONCLUSIVE",
            "task_outcome": None,
            "reason": "worker_execution_or_initial_geometry_error",
        }
    placement.save(directory / "receipt.json", result)
    placement.save(directory / "measurement.json", capability.case_measure(directory, result))
    files = [p for p in directory.rglob("*") if p.is_file() and p.name != "run.log"]
    placement.save(
        directory / "evidence_manifest.json",
        {str(p.relative_to(directory)): search.sha(p) for p in files},
    )
    return 0 if result["status"] == "VALID" else 1


def live_case(root, index, c):
    directory = root / f"attempt_{index:05d}"
    command = [
        c["robot"]["python"],
        "-u",
        str(Path(__file__).resolve()),
        "_worker",
        "--output",
        str(root),
        "--index",
        str(index),
    ]
    observer = Observer(directory)
    display(
        observer,
        phase="경계·장애물 개발 검증 시작",
    )
    with (directory / "run.log").open("x") as log:
        child = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            start_new_session=True,
        )
        try:
            while child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    display(observer)
        except KeyboardInterrupt:
            stop_group(child)
            raise
    display(observer, phase=f"개발 실행 종료 코드 {child.returncode}")
    return child.returncode


def show(report):
    for row in report["cases"]:
        measurement = row["measurement"]
        contact = measurement.get("contact")
        fall = measurement.get("fell_below_table")

        def text(value):
            return "미확인" if value is None else "있음" if value else "없음"

        print(
            f"{row['case']}: {row['task_outcome'] or row['execution_status']} | "
            f"장애물 접촉 {text(contact)} | 테이블 아래 낙하 {text(fall)}"
        )
    boundary = report["task_boundary"]
    print("작업 성공 경계:", boundary["status"])
    for interval in boundary["intervals"]:
        print(
            f"  {interval['left']['case']}({interval['left']['outcome']}) ↔ "
            f"{interval['right']['case']}({interval['right']['outcome']}), "
            f"목표 위치 간격 {interval['plate_path_width_m'] * 100:.1f}cm"
        )
    print("원인·회피 능력은 이 결과만으로 확정하지 않습니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "op", choices=["plan", "init", "run", "status", "report", "audit", "_worker"]
    )
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-new-attempts", type=int, default=1)
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.op == "_worker":
        return worker(root, args.index)
    if args.op in ("plan", "init", "audit"):
        suite = capability.validate_suite(search.read(args.config))
        c = suite["experiment"]
    else:
        m = search.read(root / "manifest.json")
        if search.sha(root / "manifest.json") != (root / "manifest.sha256").read_text().strip():
            raise ValueError("suite manifest changed")
        suite = capability.validate_suite(m["suite"])
        c = suite["experiment"]
    if args.op == "plan":
        print(
            json.dumps(
                {
                    "cases": suite["cases"],
                    "robot_attempt_cap": len(suite["cases"]),
                    "step_cap": len(suite["cases"]) * 300,
                    "afs_requests": 0,
                },
                indent=2,
            )
        )
    elif args.op == "init":
        manifest = search.freeze(c, suite_sources(c))
        manifest.update(mode="capability_suite", suite=suite)
        root.mkdir(parents=True, exist_ok=False)
        placement.save(root / "manifest.json", manifest)
        (root / "manifest.sha256").write_text(search.sha(root / "manifest.json") + "\n")
        print("PREPARED", root, "; no API/policy/robot execution")
    elif args.op == "run":
        if not args.live or not 1 <= args.max_new_attempts <= len(suite["cases"]):
            raise ValueError("explicit --live and bounded --max-new-attempts required")
        search.verify(root)
        spent = 0
        for i, case in enumerate(suite["cases"]):
            d = root / f"attempt_{i:05d}"
            if (d / "receipt.json").exists():
                check_evidence(d)
                if search.read(d / "receipt.json")["status"] != "VALID":
                    raise RuntimeError("previous exclusion preserved; no replacement")
                continue
            if spent >= args.max_new_attempts:
                break
            if (d / "robot_intent.json").exists():
                raise RuntimeError("pending case intent; never resend or rerun")
            d.mkdir(exist_ok=False)
            placement.save(
                d / "manifest.json", {"mode": "manual", "config": c}
            )  # Read-only observer.
            placement.save(d / "candidate.json", case)
            placement.save(d / "robot_intent.json", case)
            print(f"CASE {i + 1}/{len(suite['cases'])} {case['id']}", flush=True)
            code = live_case(root, i, c)
            spent += 1
            if code:
                raise RuntimeError("case excluded; see run.log; no retry/replacement")
            check_evidence(d)
            print("RESULT", search.read(d / "receipt.json")["task_outcome"], flush=True)
        show(capability.report(root))
    elif args.op in ("status", "report"):
        for d in root.glob("attempt_*"):
            if (d / "evidence_manifest.json").exists():
                check_evidence(d)
        report = capability.report(root)
        if args.op == "report":
            from datetime import datetime, timezone

            target = root / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            target.mkdir(parents=True, exist_ok=False)
            placement.save(target / "report.json", report)
            print("REPORT", target / "report.json")
        show(report)
    else:
        # CPU-only creation/reset/forward, no model inference, rendering or policy actions.
        os.environ["LIBERO_CONFIG_PATH"] = c["robot"]["libero_config_path"]
        sys.path.insert(0, c["robot"]["upstream_root"])
        from libero.libero.envs.env_wrapper import ControlEnv

        task = next(p for p in legacy_cli.sources(c) if p.suffix == ".bddl")
        root.mkdir(parents=True, exist_ok=False)
        records = []
        for i, case in enumerate(suite["cases"]):
            env = ControlEnv(str(task), use_camera_obs=False, has_offscreen_renderer=False)
            try:
                env.env.set_xml_processor(
                    lambda xml, items=case["obstacles"]: obstacles.inject(xml, items)
                )
                env.seed(c["background_seed"])
                env.env.reset()
                audit = placement.apply(env, case["positions"], c["background_positions"])
                audit["obstacle_penetrations"] = obstacles.initial_check(env)
                audit["valid"] = audit["valid"] and not audit["obstacle_penetrations"]
                actual = [
                    {
                        "name": env.sim.model.geom_id2name(g),
                        "xyz_m": env.sim.data.geom_xpos[g].tolist(),
                    }
                    for g in obstacles.obstacle_ids(env)
                ]
                if len(actual) != len(case["obstacles"]):
                    raise ValueError("compiled obstacle missing")
                (root / f"scene_{i:02d}.xml").write_text(env.sim.model.get_xml())
                records.append({"case": case["id"], "audit": audit, "compiled_obstacles": actual})
            finally:
                env.close()
        placement.save(
            root / "geometry_audit.json",
            {
                "records": records,
                "policy_executed": False,
                "claim": "Initial geometry only; policy success/reachability/avoidance unverified.",
            },
        )
        print("CPU_GEOMETRY", sum(r["audit"]["valid"] for r in records), "/", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
