"""Observer reads real artifacts; subprocess tests run only tiny fake CPU programs."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/watch_robot_arm_search.py"
spec = importlib.util.spec_from_file_location("arm_progress", TOOL)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def prepared(tmp_path):
    c = {
        "seeds": [7],
        "methods": ["afs", "random"],
        "per_arm": 4,
        "robot": {"max_episode_steps": 300},
    }
    write(tmp_path / "manifest.json", {"config": c, "mode": "paired_development"})
    return tmp_path


def attempt(root):
    return root / "seed_7/afs/attempt_00000"


def test_snapshot_is_readonly_and_never_collects_receipt(prepared):
    d = attempt(prepared)
    write(d / "robot_intent.json", {})
    write(d / "receipt.json", {"status": "VALID", "task_outcome": "PASS"})
    before = {str(p): p.read_bytes() for p in prepared.rglob("*") if p.is_file()}
    snapshot = progress.Observer(prepared).snapshot()
    after = {str(p): p.read_bytes() for p in prepared.rglob("*") if p.is_file()}
    assert before == after
    assert snapshot["completed"] == 0
    assert "결과 수집" in snapshot["stage"]
    assert not (d / "result.json").exists()


def test_bootstrap_labels_and_actual_steps_incremental(prepared):
    d = attempt(prepared)
    write(d / "robot_intent.json", {})
    trace = d / "trace.jsonl"
    trace.write_text("{}\n{}")
    observer = progress.Observer(prepared)
    assert observer.snapshot()["steps"] == 1
    with trace.open("a") as stream:
        stream.write("\n{}\n")
    value = observer.snapshot()
    assert value["steps"] == 3
    assert value["step_limit"] == 300
    assert value["current"] == "seed=7 AFS 1/4"
    assert "성공 시 조기 종료" in observer.line()


def test_model_shard_progress_is_observed_not_guessed(prepared):
    d = attempt(prepared)
    write(d / "robot_intent.json", {})
    (d / "run.log").write_text("Loading checkpoint shards:  50%|###   | 1/2 [00:10]\r")
    s = progress.Observer(prepared).snapshot()
    assert s["stage"] == "모델 파일 로딩 1/2"
    assert "steps" not in s


def test_api_wait_counts_intent_not_failure(prepared):
    d = attempt(prepared)
    write(d / "request.json", {})
    s = progress.Observer(prepared).snapshot()
    assert s["request_intents"] == 1
    assert s["fail"] == 0
    assert "AFS 응답" in s["stage"]


def test_exclusions_are_separate_from_robot_failures(prepared):
    write(attempt(prepared) / "result.json", {"status": "INCONCLUSIVE", "task_outcome": None})
    write(
        prepared / "seed_7/random/attempt_00000/result.json",
        {"status": "VALID", "task_outcome": "FAIL"},
    )
    s = progress.Observer(prepared).snapshot()
    assert s["completed"] == 2 and s["fail"] == 1 and s["excluded"] == 1


def test_manual_monitor_and_incomplete_json(prepared):
    write(
        prepared / "manifest.json",
        {"config": {"robot": {"max_episode_steps": 300}}, "mode": "manual"},
    )
    write(prepared / "robot_intent.json", {})
    (prepared / "receipt.json").write_text("{")
    observer = progress.Observer(prepared)
    assert observer.snapshot()["total"] == 1
    write(prepared / "receipt.json", {"status": "VALID", "task_outcome": "PASS"})
    assert observer.snapshot()["pass"] == 1


@pytest.mark.parametrize("exit_code", [0, 23])
def test_fake_subprocess_keeps_outputs_exit_code_and_emits_heartbeat(prepared, capsys, exit_code):
    observer = progress.Observer(prepared)
    program = (
        'import sys,time; print("original output",flush=True); '
        'print("original stderr",file=sys.stderr,flush=True); '
        f"time.sleep(.15); sys.exit({exit_code})"
    )
    result = progress.run_with_progress([sys.executable, "-u", "-c", program], observer, 0.03)
    output = capsys.readouterr()
    assert result == exit_code
    assert "original output" in output.out
    assert "original stderr" in output.err
    assert "동결 검사" in output.err
    assert "결과 0/8" in output.err
    assert f"종료 코드 {exit_code}" in output.err
    assert output.err.count("[진행]") >= 3
    assert list(prepared.iterdir()) == [prepared / "manifest.json"]


def test_once_does_not_launch_process(prepared, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(TOOL), "--output", str(prepared), "--once"])
    monkeypatch.setattr(
        progress.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected start")
    )
    assert progress.main() == 0
    assert "관찰만" in capsys.readouterr().err
