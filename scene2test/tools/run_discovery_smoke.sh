#!/usr/bin/env bash
# Freeze, initialize and execute ONE new evaluation attempt. Never resumes implicitly.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash tools/run_discovery_smoke.sh --live | --dry-run' \
    '  --live     동결 → 초기화 → 유료 초기 장면 1회 실행' \
    '  --dry-run  명령만 출력; 파일 생성 및 API/로봇 실행 없음'
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

config="${AFS_EVAL_CONFIG:-config/discovery_evaluation_luna.json}"
control_run="${AFS_CONTROL_RUN:-/workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout}"
plan_dir="${AFS_EVAL_PLAN_DIR:-/workspace/g1_failure/runtime/discovery_evaluation/independent_luna_plan_v1}"
campaign_dir="${AFS_EVAL_CAMPAIGN_DIR:-/workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v1}"

freeze=(uv run --no-sync python tools/prepare_discovery_evaluation.py freeze
  --config "$config" --run "$control_run" --output-dir "$plan_dir")
initialize=(uv run --no-sync python tools/run_discovery_evaluation.py init
  --manifest "$plan_dir/manifest.json" --campaign "$campaign_dir")
execute=(uv run --no-sync python tools/run_discovery_evaluation.py run
  --campaign "$campaign_dir" --live --max-new-attempts 1)

if [[ "$mode" == --dry-run ]]; then
  printf '작업 디렉터리: %s\n' "$project_dir"
  printf '%q ' "${freeze[@]}"; printf '\n'
  printf '%q ' "${initialize[@]}"; printf '\n'
  printf '%q ' "${execute[@]}"; printf '\n'
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  printf '오류: uv 명령어가 필요합니다.\n' >&2
  exit 2
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  printf '오류: 먼저 OPENAI_API_KEY를 설정하세요. 키는 출력하지 않습니다.\n' >&2
  exit 2
fi
if [[ ! -f "$config" || ! -d "$control_run" ]]; then
  printf '오류: 평가 설정 파일 또는 기준 rollout 디렉터리가 없습니다.\n' >&2
  exit 2
fi
for output in "$plan_dir" "$campaign_dir"; do
  if [[ -e "$output" || -L "$output" ]]; then
    printf '오류: 출력 경로가 이미 존재합니다: %s\n' "$output" >&2
    printf '덮어쓰기·자동 재개하지 않습니다. 기존 결과를 먼저 확인하세요.\n' >&2
    exit 2
  fi
done

step='계획 동결'
trap 'exit_status=$?; printf "중단: %s 단계 실패(종료 코드 %s). 자동 재시도하지 않습니다.\n" "$step" "$exit_status" >&2; exit "$exit_status"' ERR
printf '[1/3] 계획 동결 — API 호출 없음\n'
"${freeze[@]}"
step='캠페인 초기화'
printf '[2/3] 캠페인 초기화 — API 호출 없음\n'
"${initialize[@]}"
step='초기 장면 1회 실행'
printf '[3/3] 유료 초기 장면 1회 실행 — 로봇 API 최대 10회(기본 설정)\n'
"${execute[@]}"
printf '완료: 이번 호출에서 새 시도 최대 1회. 캠페인: %s\n' "$campaign_dir"
