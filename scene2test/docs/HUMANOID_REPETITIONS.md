# AFS / Random 독립 3회 반복

새 seed 75101, 75102, 75103에서 AFS 7회 + Random 7회를 각각 실행합니다.
총 42회의 새 실험이며, 기존 결과는 포함하지 않습니다. 각 방법의 7회에는
새로 실행하는 기준 장면 1회, 변수 1개 변경 3회, 변수 2개 변경 3회가 포함됩니다.
기존의 특정 실패 장면을 세 번 재현하는 절차와는 다릅니다.

준비된 실험은 아래 한 명령으로 순서대로 실행합니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_repetitions.sh --live 2>&1 | tee zz_run_humanoid_repetitions.log
```

OpenRouter `openai/gpt-6-luna`를 로봇과 AFS에 사용합니다. 에피소드당 로봇
호출 20회, HTTP 대기 600초, 실행기 마감 653초, 명시적 출력 상한 128000을
유지합니다. 세트당 최대 14개 에피소드·280회 로봇 호출·9회 AFS 제안이며,
전체 상한은 42개·840회·27회입니다. 기존 검증된 control은 설정 검증에만
참조하고 평가 이력으로 가져오지 않습니다. 추가 control 실행은 없습니다.

seed와 방법별 이력은 분리됩니다. Random은 같은 기준 장면에서 변수를 1/2개
무작위로 고르며 이전 결과로 다음 추출을 변경하지 않습니다. 각 세트의 새로운
기준 장면이 PASS여야 해당 세트의 환경 시험을 계속합니다. 모델 API 생성의
결정적 재현을 보장하는 seed 설정은 아니며, 환경 탐색의 seed를 고정한 것입니다.

실행 중 결과 이벤트와 30초 간격 진행 표시가 나옵니다. 한 세트가 오류로 멈추면
그 상태를 보존하고 다른 독립 세트를 진행합니다. 요청 자동 재전송·제외 대체·
예산 초기화는 하지 않습니다. 완료된 세트는 다시 실행되지 않습니다. 오류가
있는 경우 전체 종료 코드는 0이 아닙니다. Ctrl+C는 나머지 세트도 시작하지 않습니다.

상태 확인과 계획 확인은 새 API나 로봇을 실행하지 않습니다.

```bash
bash tools/run_humanoid_repetitions.sh --status
bash tools/run_humanoid_repetitions.sh --dry-run
```

결과 폴더: `development/humanoid_repetitions3_20261024_v1/`.
각 `seed_<번호>/reports/<시간>/report.html`에 목표 실패·안전 이벤트 보고서와
영상 링크가 저장됩니다. 전체 목표 결과는 `replication_summary.json`과
`replication_summary.txt`에 집계합니다. 세 세트 모두 동일한 유효 예산과
변경 개수로 완료됐을 때만 평균 실패 발견률·세트 간 표본 표준편차·방법 간
차이를 계산합니다. 미완료 세트는 숨기거나 평균에서 조용히 제외하지 않습니다.

이번 실험은 이미 선택한 개발용 환경 범위에서의 반복 측정입니다. 이전 결과와
합산해 새로운 독립 표본처럼 세지 않습니다. 목표 PASS는 사람 안전을 의미하지
않으며 안전 이벤트는 각 세트의 보고서에서 따로 확인합니다. 세 번의 반복으로
자동으로 통계적 우위가 확정되는 것은 아닙니다.
