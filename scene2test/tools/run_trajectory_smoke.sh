#!/usr/bin/env bash
# Fresh 10-call control, then at most one AFS request and one new robot episode.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash tools/run_trajectory_smoke.sh --dry-run | --live' \
    '  --dry-run  실행 계획만 출력; 파일 생성·API·로봇 실행 없음' \
    '  --live     기준 실행 1회(10호출) → 검증 → 새 AFS 탐색 최대 1회' \
    '  이번 호출 상한: 로봇 API 정책호출 20회 + AFS 요청 1회' \
    '  환경변수: AFS_TRAJECTORY_SOURCE_SCENE, AFS_TRAJECTORY_OUTPUT_DIR' \
    '  기존 출력은 덮어쓰거나 자동 재개하지 않습니다.'
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi
case "$1" in
  --live|--dry-run) mode="$1" ;;
  --help|-h) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
config="$project_dir/config/afs_trajectory_luna.json"
source_scene="${AFS_TRAJECTORY_SOURCE_SCENE:-/workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v2_development/seeds/17/attempts/attempt_00004/scene_config.json}"
trial_root="${AFS_TRAJECTORY_OUTPUT_DIR:-/workspace/g1_failure/runtime/trajectory_feedback/$(date -u +%Y%m%dT%H%M%S)_$$}"

control=(uv run --no-sync python tools/run_robot_goal_agent.py
  --live --scene-config "$source_scene" --model gpt-6-luna --enable-push
  --navigation-completion goal_dwell_v1 --evaluation-profile goal_outcome_v1
  --response-timeout 300 --max-calls 10 --run-dir "$trial_root/control")

if [[ "$mode" == --dry-run ]]; then
  printf '작업 디렉터리: %s\n새 출력: %s\n' "$project_dir" "$trial_root"
  printf '%q ' "${control[@]}"; printf '\n'
  printf '%s\n' \
    '기준 result/manifest 검증: VALID PASS/FAIL만 허용; 판정 불가이면 중단' \
    "새 AFS 세션: $trial_root/afs; 설정: $config" \
    'AFS run: max_new_attempts=1, max_new_afs_requests=1; 자동 재개/장면 재시도 없음' \
    "로그: $trial_root/run.log 및 $project_dir/zz_log.log" \
    '15회 진단은 입력하지 않으며, 기존 캠페인과 예산은 그대로 보존합니다.'
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  printf '오류: uv 명령어가 필요합니다.\n' >&2
  exit 2
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  printf '오류: OPENAI_API_KEY를 먼저 설정하세요. 키는 출력하지 않습니다.\n' >&2
  exit 2
fi
if [[ ! -f "$config" || ! -f "$source_scene" ]]; then
  printf '오류: 설정 또는 원본 scene_config.json 파일이 없습니다.\n' >&2
  exit 2
fi
if [[ "$trial_root" != /* || -e "$trial_root" || -L "$trial_root" ]]; then
  printf '오류: 존재하지 않는 절대 출력 경로가 필요합니다: %s\n' "$trial_root" >&2
  exit 2
fi
mkdir -p -- "$(dirname -- "$trial_root")"
mkdir -- "$trial_root"

(
  step='기준 실행'
  trap 'code=$?; printf "중단: %s (종료 코드 %s). 자동 장면 재실행 없음.\n" "$step" "$code" >&2; exit "$code"' ERR
  printf 'TRIAL_ROOT=%s\nLOG=%s/run.log\n' "$trial_root" "$trial_root"
  printf '[1/3] 유료 기준 실행 — 로봇 정책호출 최대 10회\n'
  "${control[@]}"

  step='기준 기록 검증'
  printf '[2/3] 기준 기록 검증 — API 호출 없음\n'
  uv run --no-sync python - validate "$trial_root/control" <<'PY'
import sys
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_goal_run, read_json
from failure_client.evaluation.research_records import RunInput

root = Path(sys.argv[2])
record = read_goal_run(RunInput(path=str(root)))
if record.status != "VALID" or record.task_outcome not in {"PASS", "FAIL"}:
    raise SystemExit("기준 실행 판정 불가: 새 AFS를 시작하지 않습니다.")
protocol = read_json(root / "protocol.json")
if protocol["max_calls"] != 10 or protocol["model"] != "gpt-6-luna":
    raise SystemExit("기준 모델/예산이 예상 조건과 다릅니다.")
print(f"CONTROL={record.status}/{record.task_outcome}; 새 탐색과 별도 비용으로 보존")
PY

  step='새 AFS 탐색'
  printf '[3/3] 새 피드백 탐색 — AFS 최대 1요청·새 로봇 실행 최대 1회\n'
  uv run --no-sync python - search "$trial_root" "$config" <<'PY'
import json
import sys
from pathlib import Path

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget
from robot_vlm.debug_log import clean

root, config = map(Path, sys.argv[2:])
budget = SearchBudget.model_validate_json(config.read_text())
session = AutonomousAFS.create(root / "afs", [root / "control"], budget)
engine = AutonomousAFS(
    session,
    on_event=lambda event: print(
        "AUTONOMOUS_EVENT=" + json.dumps(event, ensure_ascii=False), flush=True
    ),
)
print(f"AFS_AUTONOMOUS={engine.root}", flush=True)
try:
    summary = engine.run(live=True, max_new_attempts=1, max_new_afs_requests=1)
except Exception as exc:
    print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}", flush=True)
    raise SystemExit(2)
finally:
    print(f"REPORT={engine.report()}", flush=True)
compact = {k: summary.get(k) for k in (
    "status", "reason", "attempted", "valid", "pass", "fail", "excluded",
    "afs_requests_attempted", "afs_proposals_rejected",
)}
compact["discovered_families"] = sorted({
    f for g in summary["new_only_discovery_metrics"]["groups"]
    for f in g["discovered_families"]
})
print("SUMMARY=" + json.dumps(compact, ensure_ascii=False), flush=True)
if summary["status"] == "NEEDS_ATTENTION":
    raise SystemExit(2)
PY
  printf '완료: 기준 최대 1회 + 새 탐색 최대 1회. 전체 예산 완료를 뜻하지 않습니다.\n'
  printf 'TRIAL_ROOT=%s\nLOG=%s/run.log\n' "$trial_root" "$trial_root"
) 2>&1 | tee "$trial_root/run.log" "$project_dir/zz_log.log"
