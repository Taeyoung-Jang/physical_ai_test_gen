# length 응답에 한정한 로봇 추론 강도 하향

OpenRouter `openai/gpt-6-luna` 로봇 행동 선택은 매 에피소드에서 high로
시작합니다. HTTP 200으로 정상 수신한 동일 모델의 응답이 `length`로
종료됐다고 확인되면 medium, low, none 순서로 한 단계씩 낮춰 다음 호출을
수행합니다. 낮춘 강도는 해당 에피소드에서 유지하고 다음 에피소드에서는
다시 high로 시작합니다. AFS 환경 제안은 기존 medium을 유지합니다.

잘린 응답의 행동은 실행하지 않습니다. 다음 호출에는 최신 카메라·환경 상태를
다시 관측해 전달합니다. 각 호출은 별도 request ID, 응답 ID, 사용량 기록을
가지며 기존 에피소드당 20회 호출 예산을 한 회씩 소모합니다. 성공한 행동만
20회로 세고 재시도를 추가로 지출하는 방식이 아닙니다. none에서도 length이거나
남은 호출 예산이 없으면 불완전 실행으로 중단합니다.

HTTP 오류, timeout, JSON/스키마 오류, content_filter 등은 이 규칙으로 재시도하지
않습니다. 기존의 확인된 전송 전 TCP 연결 재시도 규칙은 그대로입니다. 저장된
이전 실험 요청도 재전송하지 않습니다. 호출이 종료된 후에는 단계 하향 요청을
새로 보내지 않습니다.

출력 상한은 128000, HTTP 읽기 대기는 600초입니다. 앞선 128000토큰 length
응답이 약 850초에 도착했으므로, 이 정책의 실행기 wall deadline은 호출당
1200초로 설정합니다. 1200초까지 응답 상태를 확인할 수 없으면 중단합니다.
단계 하향 정책·실제 마감·출력 상한은 protocol.json과 API 로그에 기록합니다.
기존 high 고정 실험과 다른 로봇 조건이므로 결과를 합쳐 비교하지 않습니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_reasoning_fallback.sh --live 2>&1 | tee zz_run_humanoid_reasoning_fallback.log
```

새 폴더 `development/humanoid_reasoning_fallback3_20261024_v1/`에서 새 조건의
공통 기준 1회를 먼저 확인하고 AFS7+Random7을 3세트 실행합니다. 세트 안의
기준 실행은 각 방법의 7회에 포함됩니다. 총 상한은 공통 기준을 포함한
43개 에피소드·860회 로봇 호출·27회 AFS 제안입니다. 모든 재시도는 이 상한
안에 있습니다. 이전 결과는 보존합니다. 처음 준비할 때 서로 다른 seed 3개를
OS 난수로 골라 `seed_assignment.json`과 실행 로그에 저장합니다. 같은 세트의
AFS·Random은 seed를 공유합니다. 재실행은 저장된 seed를 유지하며 새로 뽑지
않습니다. 다른 조건의 이력은 가져오지 않습니다. 이미 동결된 이전 고정 seed
실험의 설정도 변경하지 않습니다. 모델 API의 결정적 출력 seed를 지정하는
기능과는 구분되며, 환경 탐색의 난수 seed를 선택하는 기능입니다.

`--dry-run`은 계획만 출력하고 `--status`는 준비된 결과만 집계합니다.
공통 기준 실행이 실패·불완전이면 보존하고 중단하며 자동 재실행하지 않습니다.
새 정책도 장시간 생성이나 HTTP 장애의 완전한 해결을 보장하지는 않습니다.
