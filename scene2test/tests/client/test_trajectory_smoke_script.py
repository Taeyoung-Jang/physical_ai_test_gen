"""Orchestration tests with an isolated project and fake uv, never live API/robot."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/run_trajectory_smoke.sh"


def setup(tmp_path):
    project = tmp_path / "isolated project"
    (project / "tools").mkdir(parents=True)
    (project / "config").mkdir()
    script = project / "tools" / SCRIPT.name
    script.write_text(SCRIPT.read_text())
    (project / "config/afs_trajectory_luna.json").write_text("{}")
    scene = tmp_path / "source scene.json"
    scene.write_text("{}")
    bins = tmp_path / "bin"
    bins.mkdir()
    fake = bins / "uv"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "stage=args[4] if args[3]=='-' else 'control'\n"
        "payload=sys.stdin.read() if args[3]=='-' else ''\n"
        "with open(os.environ['FAKE_UV_LOG'],'a') as f:\n"
        "    f.write(json.dumps({'stage':stage,'args':args,'payload':payload})+'\\n')\n"
        "print('FAKE_STAGE='+stage)\n"
        "sys.exit(7 if stage==os.getenv('FAKE_FAIL_STAGE') else 0)\n"
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(bins) + os.pathsep + os.environ["PATH"],
        "OPENAI_API_KEY": "sk-private-not-to-print",
        "AFS_TRAJECTORY_SOURCE_SCENE": str(scene),
        "AFS_TRAJECTORY_OUTPUT_DIR": str(tmp_path / "new trial with spaces"),
        "FAKE_UV_LOG": str(tmp_path / "calls.jsonl"),
    }
    return script, env


def invoke(script, env, *args):
    return subprocess.run(
        ["bash", str(script), *args],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def calls(env):
    path = Path(env["FAKE_UV_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_control_validation_search_order_and_logs_are_bounded(tmp_path):
    script, env = setup(tmp_path)
    r = invoke(script, env, "--live")
    assert r.returncode == 0, r.stdout + r.stderr
    commands = calls(env)
    assert [c["stage"] for c in commands] == ["control", "validate", "search"]
    args = commands[0]["args"]
    assert args[args.index("--max-calls") + 1] == "10"
    assert args[args.index("--scene-config") + 1] == env["AFS_TRAJECTORY_SOURCE_SCENE"]
    payload = commands[-1]["payload"]
    assert "max_new_attempts=1, max_new_afs_requests=1" in payload
    assert "--continue-after-exclusion" not in str(commands)
    assert "API_KEY" not in payload
    assert env["OPENAI_API_KEY"] not in r.stdout + r.stderr
    log = Path(env["AFS_TRAJECTORY_OUTPUT_DIR"]) / "run.log"
    assert log.read_text() == (script.parents[1] / "zz_log.log").read_text()
    assert "FAKE_STAGE=search" in log.read_text()


@pytest.mark.parametrize("stage,count", [("control", 1), ("validate", 2), ("search", 3)])
def test_failed_or_inconclusive_stage_stops_and_preserves_log(tmp_path, stage, count):
    script, env = setup(tmp_path)
    env["FAKE_FAIL_STAGE"] = stage
    r = invoke(script, env, "--live")
    assert r.returncode == 7
    assert len(calls(env)) == count
    assert "중단:" in r.stdout
    assert (Path(env["AFS_TRAJECTORY_OUTPUT_DIR"]) / "run.log").exists()


def test_existing_output_never_overwritten_or_resumed(tmp_path):
    script, env = setup(tmp_path)
    out = Path(env["AFS_TRAJECTORY_OUTPUT_DIR"])
    out.mkdir()
    keep = out / "keep.txt"
    keep.write_text("preserve")
    assert invoke(script, env, "--live").returncode == 2
    assert keep.read_text() == "preserve" and not calls(env)


def test_no_live_flag_no_key_and_dry_run_never_execute(tmp_path):
    script, env = setup(tmp_path)
    env.pop("OPENAI_API_KEY")
    assert invoke(script, env).returncode == 2
    assert invoke(script, env, "--live").returncode == 2
    r = invoke(script, env, "--dry-run")
    assert r.returncode == 0 and "max_new_afs_requests=1" in r.stdout
    assert not calls(env) and not Path(env["AFS_TRAJECTORY_OUTPUT_DIR"]).exists()


def test_bash_and_embedded_python_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", SCRIPT.read_text(), re.S)
    assert len(blocks) == 2
    for block in blocks:
        compile(block, str(SCRIPT), "exec")
