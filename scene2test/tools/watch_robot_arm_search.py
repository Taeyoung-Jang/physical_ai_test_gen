"""Read-only progress display around the unchanged frozen robot-arm runner."""

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT = PROJECT / "experiments/robot_arm_libero/placement_wide_v1"


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def tail(path, limit=65536):
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


class Observer:
    def __init__(self, root):
        self.root = Path(root).resolve()
        manifest = read_json(self.root / "manifest.json")
        if not manifest:
            raise ValueError("준비된 manifest.json을 찾을 수 없습니다: " + str(self.root))
        self.config = manifest["config"]
        self.manual = manifest.get("mode") == "manual"
        self.steps = {}

    def count_steps(self, path):
        try:
            stat = path.stat()
        except OSError:
            return 0
        previous = self.steps.get(path, (None, 0, 0))
        inode, offset, count = previous
        if inode != stat.st_ino or stat.st_size < offset:
            offset, count = 0, 0
        with path.open("rb") as stream:
            stream.seek(offset)
            for block in iter(lambda: stream.read(65536), b""):
                count += block.count(b"\n")
            offset = stream.tell()
        self.steps[path] = (stat.st_ino, offset, count)
        return count

    def directories(self):
        if self.manual:
            return [("수동 배치", self.root)]
        c = self.config
        return [
            (
                f"seed={seed} {method.upper()} {index + 1}/{c['per_arm']}",
                self.root / f"seed_{seed}" / method / f"attempt_{index:05d}",
            )
            for index in range(c["per_arm"])
            for seed in c["seeds"]
            for method in c["methods"]
        ]

    def snapshot(self):
        directories = self.directories()
        done = passed = failed = excluded = 0
        pending = []
        requests = 0
        for label, directory in directories:
            result = read_json(directory / "result.json")
            if self.manual:
                result = result or read_json(directory / "receipt.json")
            if result:
                done += 1
                if result.get("status") != "VALID":
                    excluded += 1
                elif result.get("task_outcome") == "PASS":
                    passed += 1
                elif result.get("task_outcome") == "FAIL":
                    failed += 1
            elif any(
                (directory / name).exists()
                for name in ("request.json", "robot_intent.json", "candidate.json")
            ):
                pending.append((label, directory))
            requests += int((directory / "request.json").exists())
        result = {
            "completed": done,
            "total": len(directories),
            "pass": passed,
            "fail": failed,
            "excluded": excluded,
            "request_intents": requests,
            "pending": len(pending),
        }
        if not pending:
            result["stage"] = (
                "모든 결과 기록 완료"
                if done == len(directories)
                else "소스·모델 동결 검사 또는 다음 작업 대기"
            )
            return result
        label, directory = pending[0]
        result.update(current=label, log=str(directory / "run.log"))
        if not self.manual:
            index = int(directory.name.split("_")[-1])
            result["selection_phase"] = (
                "공통 초기 배치 (AFS 호출 없음)"
                if index < self.config.get("bootstrap", 2)
                else "AFS 제안 배치"
                if directory.parent.name == "afs"
                else "Random 배치"
            )
        request = directory / "request.json"
        if request.exists() and not (directory / "response.json").exists():
            result["stage"] = "AFS 응답 대기 (기존 요청 기록; 재전송하지 않음)"
        elif not (directory / "robot_intent.json").exists():
            result["stage"] = "위치 후보 생성·응답 검증"
        elif (directory / "receipt.json").exists():
            result["stage"] = "로봇 결과 수집·저장 대기"
        else:
            count = self.count_steps(directory / "trace.jsonl")
            log = tail(directory / "run.log")
            if "Traceback (most recent call last)" in log:
                result["stage"] = "오류 로그 감지 (원본 실행기 종료/분류 확인 필요)"
            elif count:
                result["stage"] = "로봇 작업 수행 / 추론 대기"
                result["steps"] = count
                result["step_limit"] = self.config["robot"]["max_episode_steps"]
            elif (directory / "initial_state.json").exists():
                result["stage"] = "초기 위치 적용·검사 / 첫 행동 준비"
                audit = read_json(directory / "initial_state.json")
                if audit and not audit.get("valid", True):
                    result["stage"] = "초기 배치 검사 제외"
            elif "Running collecting" in log or "Episodes:" in log:
                result["stage"] = "환경·카메라 초기화 / 첫 추론 준비"
            else:
                shards = re.findall(
                    r"Loading checkpoint shards:\s*(\d+)%[^\r\n]*?\|\s*(\d+)/(\d+)", log
                )
                result["stage"] = "하위 실행기 동결 검사·라이브러리/모델 준비"
                if shards:
                    _, n, total = shards[-1]
                    result["stage"] = f"모델 파일 로딩 {n}/{total}"
                    if n == total:
                        result["stage"] += " / 환경 준비"
        times = []
        for name in ("run.log", "trace.jsonl", "request.json", "response.json", "receipt.json"):
            try:
                times.append((directory / name).stat().st_mtime)
            except OSError:
                pass
        result["record_age_seconds"] = max(0, int(time.time() - max(times))) if times else None
        return result

    def line(self):
        s = self.snapshot()
        text = (
            f"결과 {s['completed']}/{s['total']} | PASS {s['pass']} "
            f"FAIL {s['fail']} 제외 {s['excluded']} | AFS 요청 기록 {s['request_intents']}"
        )
        if "current" in s:
            text += " | " + s["current"]
        if "selection_phase" in s:
            text += " | " + s["selection_phase"]
        text += " | " + s["stage"]
        if "steps" in s:
            text += f" | 실제 step {s['steps']}/최대 {s['step_limit']} (성공 시 조기 종료)"
        if s.get("record_age_seconds") is not None:
            text += f" | 마지막 기록 {s['record_age_seconds']}초 전"
        return text


def display(observer, *, observing_only=False, phase=None):
    label = "기록 관찰" if observing_only else "진행"
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        line = observer.line()
    except (OSError, ValueError, KeyError):
        line = "기록 갱신 중; 다음 표시에서 다시 확인"
    if phase:
        line = phase + " | " + line
    print(f"[{timestamp}] [{label}] {line}", file=sys.stderr, flush=True)


def stop_group(child):
    """Interrupt only the subprocess tree this wrapper started."""
    for sig, seconds in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            return
        try:
            child.wait(timeout=seconds)
            return
        except subprocess.TimeoutExpired:
            continue


def run_with_progress(command, observer, interval=5):
    # Unbuffer the original parent and inherited worker stdout; no policy/settings edits.
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    display(observer, phase="원본 실행기 시작; 소스·모델 동결 검사를 기다립니다")
    child = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
        start_new_session=True,
    )
    messages = queue.Queue()

    def pump(stream, destination):
        try:
            for line in stream:
                messages.put((destination, line))
        finally:
            stream.close()
            messages.put((destination, None))

    threads = [
        threading.Thread(target=pump, args=(child.stdout, sys.stdout), daemon=True),
        threading.Thread(target=pump, args=(child.stderr, sys.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    closed = 0
    next_display = time.monotonic() + interval
    try:
        while closed < 2 or child.poll() is None:
            try:
                destination, line = messages.get(timeout=min(interval, 0.2))
                if line is None:
                    closed += 1
                else:
                    destination.write(line)
                    destination.flush()
            except queue.Empty:
                pass
            if time.monotonic() >= next_display:
                display(observer)
                next_display = time.monotonic() + interval
        code = child.wait()
    except KeyboardInterrupt:
        print(
            "\n진행 실행에 중단 신호를 전달합니다. 저장된 요청은 자동 재시도하지 않습니다.",
            file=sys.stderr,
            flush=True,
        )
        stop_group(child)
        code = 130
    finally:
        for thread in threads:
            thread.join(timeout=1)
    display(observer, phase=f"원본 실행기 종료 코드 {code}")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Start unchanged original runner")
    mode.add_argument("--watch-only", action="store_true", help="Observe only; never start a run")
    parser.add_argument(
        "--once", action="store_true", help="Read one snapshot without starting a run"
    )
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--max-new-attempts", type=int, default=1)
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 60:
        parser.error("--interval must be 0.1..60 seconds")
    if args.live and args.once:
        parser.error("--once cannot start a live run")
    observer = Observer(args.output)
    if not args.live:
        print(
            "관찰만 수행합니다. 저장 기록만으로 실행 중/중단 여부는 확정할 수 없습니다. "
            "Ctrl+C는 감시 화면만 종료합니다.",
            file=sys.stderr,
            flush=True,
        )
        try:
            while True:
                display(observer, observing_only=True)
                if args.once:
                    return 0
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
    if not 1 <= args.max_new_attempts <= 24:
        parser.error("--max-new-attempts must be 1..24")
    command = [
        sys.executable,
        "-u",
        str(PROJECT / "tools/run_robot_arm_search.py"),
        "manual-run" if observer.manual else "run",
        "--live",
        "--output",
        str(observer.root),
    ]
    if not observer.manual:
        command += ["--max-new-attempts", str(args.max_new_attempts)]
    return run_with_progress(command, observer, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
