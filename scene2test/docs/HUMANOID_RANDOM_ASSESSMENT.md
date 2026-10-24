# 휴머노이드 Random 10회 평가

기존 AFS 평가와 분리된 Random 전용 실행입니다. 같은 기준 장면, 21개 변수의 범위,
로봇 설정을 사용합니다. 총 10회에 기준 장면 확인 1회가 포함됩니다. 나머지 9회는
매번 기준 장면에서 출발하여 변수 1개/2개를 번갈아 무작위로 선택하고 값을 바꿉니다.
이전 장면에 변경을 누적하거나 결과에 따라 다음 장면을 고르지 않습니다.

AFS 제안 호출은 0회입니다. 로봇 Agent는 OpenRouter의
`openai/gpt-6-luna-pro`를 그대로 사용하므로 `OPENROUTER_API_KEY`가 설정된
터미널에서 실행해야 합니다. 로봇 API 호출 상한은 전체 100회입니다.

## 실행

기본 준비본은 이미 생성되어 있습니다. `init`을 다시 실행하지 마십시오.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python -u tools/run_humanoid_random_assessment.py run --live
```

각 테스트의 결과, 변경한 변수, 누적 PASS/FAIL/제외 건수를 즉시 출력합니다.
실행 중에는 30초마다 현재 단계를 표시하고, 마지막에는 터미널 요약과
HTML/텍스트/JSON 보고서를 저장합니다. 보고서 생성에 추가 LLM 호출은 없습니다.

상태만 확인하려면 다음 명령을 사용합니다. 새 API나 로봇 실행은 없습니다.

```bash
uv run --no-sync python tools/run_humanoid_random_assessment.py status
```

결과 경로:

```text
development/humanoid_random_assessment_10_20261023_v1/
  assessment_reports/<시간>/report.html
  assessment_reports/<시간>/summary.txt
  assessment_reports/<시간>/summary.json
  seeds/75001/random/
```

API 오류·제외 또는 기준 장면 검증 실패 시 중단하고 부분 결과를 보존합니다.
제외를 로봇 실패로 세지 않으며, 자동 재시도나 대체 실행은 하지 않습니다.
10회는 실행 시도 상한이므로 제외가 생기면 유효 결과는 10개보다 적습니다.
완료된 준비본을 다시 실행해도 새로운 테스트를 시작하지 않습니다.

이 평가는 고정된 로봇/Agent의 개발용 국소 취약점 탐색입니다. 보고서의 관측
실패와 물리적 원인 확정은 구분하며, 목표 도달 여부와 사람 관련 안전 이벤트도
따로 보고합니다. Random 단독 결과로 AFS의 통계적 우위를 주장하지 않습니다.
