# 응답 대기 600초

사용자 승인으로 HTTP 응답 대기 상한을 600초로 확장했습니다. 실행기 마감은
연결·처리 여유 53초를 더한 653초입니다. AFS 제안 대기도 600초입니다.
기존 기본값, 모델, 로봇 제어, 변수 범위, 재시도 규칙은 유지합니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_tests.sh both 2>&1 | tee zz_run_humanoid_timeout600.log
```

`afs` 또는 `random`으로 한 방법만 선택할 수도 있습니다.

새 시간 설정은 기존 동결 결과와 분리하여
`development/humanoid_timeout600_20261023_v2/`에 저장합니다.
최초 실행에는 새로운 코드·시간 설정을 검증하는 공통 기준 실행 1회가 추가됩니다.
이후 AFS와 Random을 각각 최대 10회 실행합니다. 공통 기준 실행 결과는 각 방법의
결과 수에 복사해 넣지 않습니다. 모든 실행에서 OpenRouter의
`openai/gpt-6-luna-pro`를 사용합니다.

부분 실행·오류가 있는 기준 폴더를 자동 삭제하거나 다시 실행하지 않습니다.
각 방법도 제외 시 자동 재시도하지 않습니다. `both`에서는 AFS 중단 후에도
독립된 Random을 진행하고, 전체 명령은 중단 상태를 나타내는 종료 코드를 유지합니다.
새 응답 정책이 적용된 실제 실행은 사용자가 위 명령을 실행할 때 시작됩니다.

공유 소스 변경으로 이전 동결 준비본의 직접 live 재개는 소스 검증에 걸립니다.
이전 결과는 보존하며 위 Bash의 새 준비본을 사용해야 합니다.
