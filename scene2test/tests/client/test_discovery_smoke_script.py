"""Bash orchestration tests with a fake uv; no API, renderer or actual campaign."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/run_discovery_smoke.sh"


def setup(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "with open(os.environ['FAKE_UV_LOG'],'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "sys.exit(7 if sys.argv[5] == os.getenv('FAKE_FAIL_STEP') else 0)\n"
    )
    fake_uv.chmod(0o755)
    control = tmp_path / "control with spaces"
    control.mkdir()
    config = tmp_path / "config.json"
    config.write_text("{}")
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "OPENAI_API_KEY": "test-key-never-print",
        "FAKE_UV_LOG": str(tmp_path / "calls.jsonl"),
        "AFS_CONTROL_RUN": str(control),
        "AFS_EVAL_CONFIG": str(config),
        "AFS_EVAL_PLAN_DIR": str(tmp_path / "new plan"),
        "AFS_EVAL_CAMPAIGN_DIR": str(tmp_path / "new campaign"),
    }
    return env


def invoke(env, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def calls(env):
    path = Path(env["FAKE_UV_LOG"])
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def test_three_commands_in_order_and_exactly_one_attempt(tmp_path):
    env = setup(tmp_path)
    result = invoke(env, "--live")
    assert result.returncode == 0, result.stderr
    commands = calls(env)
    assert [c[4] for c in commands] == ["freeze", "init", "run"]
    assert commands[-1][-3:] == ["--live", "--max-new-attempts", "1"]
    assert env["AFS_CONTROL_RUN"] in commands[0]
    assert "--continue-after-exclusion" not in commands[-1]
    assert env["OPENAI_API_KEY"] not in result.stdout + result.stderr


@pytest.mark.parametrize("stage,count", [("freeze", 1), ("init", 2), ("run", 3)])
def test_failure_stops_without_retry(tmp_path, stage, count):
    env = setup(tmp_path)
    env["FAKE_FAIL_STEP"] = stage
    result = invoke(env, "--live")
    assert result.returncode == 7
    assert len(calls(env)) == count


@pytest.mark.parametrize("which", ["AFS_EVAL_PLAN_DIR", "AFS_EVAL_CAMPAIGN_DIR"])
def test_existing_output_stops_before_any_command(tmp_path, which):
    env = setup(tmp_path)
    Path(env[which]).mkdir()
    assert invoke(env, "--live").returncode == 2
    assert not calls(env)


def test_dry_run_and_no_flag_do_not_execute(tmp_path):
    env = setup(tmp_path)
    env.pop("OPENAI_API_KEY")
    assert invoke(env).returncode == 2
    result = invoke(env, "--dry-run")
    assert result.returncode == 0
    assert "--max-new-attempts 1" in result.stdout
    assert not calls(env)
    assert not Path(env["AFS_EVAL_PLAN_DIR"]).exists()
    assert invoke(env, "--live").returncode == 2
    assert not calls(env)
