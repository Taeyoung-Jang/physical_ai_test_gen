"""One recorded subprocess attempt; never retries or repairs a robot archive."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .research_protocol import PROJECT


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            pending = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        pending = None
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def command(config, scene, run_dir):
    robot = config.robot
    args = [
        sys.executable,
        str(PROJECT / "tools/run_robot_goal_agent.py"),
        "--live",
        "--model=" + robot.model,
        "--max-calls",
        str(robot.max_calls),
        "--response-timeout",
        str(robot.response_timeout),
        "--evaluation-profile",
        "goal_outcome_v1",
        "--groot-root",
        robot.groot_root,
        "--scene-config",
        str(scene),
        "--run-dir",
        str(run_dir),
    ]
    if robot.enable_push:
        args.append("--enable-push")
    if robot.max_seconds is not None:
        args.extend(["--max-seconds", str(robot.max_seconds)])
    return args


class LocalGoalRunner:
    def __call__(self, config, attempt_dir, parameters):
        attempt_dir = Path(attempt_dir)
        run_dir = attempt_dir / "rollout"
        if run_dir.exists():
            raise ValueError("refusing to launch into an existing rollout directory")
        from clear_path.contracts import Fixture

        scene = attempt_dir / "scene_config.json"
        atomic_json(scene, Fixture(**parameters).model_dump())
        args = command(config, scene, run_dir)
        atomic_json(attempt_dir / "command.json", {"argv": args, "automatic_retries": 0})
        start = time.monotonic()
        interrupted = None
        with (attempt_dir / "process.log").open("x") as stream:
            proc = subprocess.Popen(
                args, cwd=PROJECT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True
            )
            atomic_json(attempt_dir / "process.json", {"pid": proc.pid})
            try:
                code = proc.wait(timeout=config.robot.watchdog_wall_s)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                interrupted = type(exc).__name__
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                code = proc.returncode
        receipt = {
            "returncode": code,
            "wall_s": time.monotonic() - start,
            "interrupted": interrupted,
        }
        atomic_json(attempt_dir / "receipt.json", receipt)
        return receipt
