# Luna로 남은 실행 예산 사용

현재 사용자가 승인한 예산은 **에피소드당 로봇 호출 20회**입니다. 아래 명령을
사용하십시오. 기존 10회 기준 실행의 FAIL은 보존하며 새 폴더에서 시작합니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_luna_20calls.sh both 2>&1 | tee zz_run_humanoid_luna_20calls.log
```

모델은 OpenRouter `openai/gpt-6-luna`, HTTP 대기는 600초, 실행기 마감은
653초입니다. 공통 기준과 두 방법 모두 20회 호출을 사용합니다. 환경 시험
횟수는 AFS 6회·Random 2회로 유지하며, 별도 기준 확인 3회를 포함해 전체
최대 11개 에피소드·220회 로봇 호출·9회 AFS 제안입니다. 결과는
`development/humanoid_luna_20calls_20261023_v4/`에 저장합니다. 공통 기준이
정상 PASS여야 환경 시험을 시작하며, 기존 실패를 지우거나 자동 재시도하지 않습니다.

이하 내용은 이전 **10회 호출 예산** 구간의 기록입니다.

OpenRouter의 `openai/gpt-6-luna-pro`에서 `openai/gpt-6-luna`로 로봇과 AFS
제안 모델을 모두 변경합니다. HTTP 대기 600초, 로봇 실행기 마감 653초를 유지합니다.
Pro 결과와 동결 manifest는 수정하지 않습니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_luna_remaining.sh both 2>&1 | tee zz_run_humanoid_luna_remaining.log
```

남은 Pro 실행 슬롯은 AFS 6개, Random 2개입니다. 이를 새 모델의 환경 시험
예산으로 사용합니다. 새 모델의 기준 성능은 이전 Pro PASS로 대신할 수 없으므로
공유 기준 실행 1회와 방법별 기준 실행 1회씩, 총 3회의 기준 확인이 추가됩니다.
따라서 새 구간은 공유 기준 1회 + AFS 7회(기준 1 + 환경 6) + Random 3회
(기준 1 + 환경 2), 최대 11개 에피소드입니다. 로봇 API 상한은 110회,
AFS 제안 상한은 9회입니다.

새 결과는 `development/humanoid_luna_remaining_20261023_v3/`의
`control/`, `afs/`, `random/`에 저장합니다. `afs` 또는 `random` 인자로
한 방법만 실행할 수도 있습니다.

새 seed 75002에서 동일한 변수 범위와 기준 환경을 사용하고, 1개/2개 변경
사이클과 Random 추출은 새로 시작합니다. 이전 미사용 Random 장면을 그대로
재현하는 실행은 아닙니다. AFS에는 Pro 이력이나 다른 방법의 결과를 넘기지 않습니다.
Pro와 Luna 결과를 합산해 단일 모델의 실패율이나 AFS 우위를 주장하지 않습니다.

원본의 현재 상태와 manifest 해시를 전환 계획에 고정했습니다. 원본 상태가
달라졌거나 미완료 요청이 생기면 새 API 호출 전에 중단합니다. 중단된 기준 실행은
자동 재전송하지 않으며, 방법별 제외도 자동 대체하지 않습니다. 기존 Pro 오류
요청 역시 재전송하지 않습니다. 계획은 `config/humanoid_luna_remaining_transition.json`
에서 확인할 수 있습니다.
