# G1 휴머노이드 AFS 10회 취약점 평가

현재 G1 시뮬레이터·Agent·제어기·목표 작업을 고정한 별도 개발 평가다.
사용자 최종 선택에 따라 **AFS만 총 10회**, Random은 실행하지 않는다.
기존 AFS/Random 완료 결과를 확대·초기화하거나 새 평가 이력으로 복사하지 않는다.
임의의 다른 휴머노이드를 바로 연결하는 범용 하드웨어 진단기는 아니다.

## 실행

준비된 평가의 기본 경로는 `development/humanoid_assessment_10_20261023_v1`,
설정은 `config/humanoid_vulnerability_10_pro.json`이다.
한 명령으로 남은 예산을 진행하고 터미널과 로컬 보고서에 결과를 표시한다.

```bash
uv run --no-sync python -u tools/run_humanoid_assessment.py run --live
```

최대10회에는 기준 장면1회와 AFS 변경 장면 최대9회가 포함된다.
기준 장면이 PASS여야 진행하며, 이후 항상 같은 기준에서 변수1개/2개를
번갈아 바꾼다. 최소 변경량은 기존 비교와 같은 정규화 범위10%다.
새 seed75001, 자체 이력만 사용한다. 기존 사용자 PASS는 설정·자원 확인과
개발 기준 선택에만 사용하고 평가 표본으로 복사하지 않는다.

상한은 **로봇 시도10회/로봇 정책 호출100회/AFS 제안 요청12회**다.
각 로봇 실행은 기존과 같은 OpenRouter `openai/gpt-6-luna-pro`, max10calls,
goal_dwell_v1, push 조건이다. AFS도 같은 OpenRouter 모델이며
`OPENROUTER_API_KEY`를 사용자 터미널에서 설정한다. 보고서 작성에는 추가
LLM 요청을 하지 않는다. 코드에서 키를 출력·저장하지 않는다.

기준 실패·제외·API/제안 검증 오류가 발생하면 중단하고 저장된 부분 결과를
요약한다. 제외는 로봇 실패로 세지 않고 시도 예산을 소비한다. 따라서
오류가 있으면 유효10회보다 적게 끝날 수 있다. 자동 재시도·대체·임의 보정은
없다. 저장된 미완료 intent는 재전송하지 않는다. 반복 실행은 남은 동일 예산을
사용하며, 이미 완료한 평가는 새 테스트 없이 저장 결과만 출력한다.
같은 경로에 init를 반복하거나 옛 캠페인의 freeze를 수정하지 않는다.

기존 응답기한353초와 HTTP read300초는 유지한다. 이 기능은 지연을 없애거나
연속 성공을 보장하는 변경이 아니다. 소스 변경 후 옛 frozen 캠페인을 재개하지 않는다.

## 터미널 출력과 보고서

각 `observed` 이벤트 직후 PASS/FAIL/제외, 변경 조건, 누적 결과를 출력한다.
긴 실행 중에는30초 간격으로 실제 단계와 경과 시간을 표시한다. 예상 완료율을
만들지 않는다. 마지막 목표 결과가 수집되면 안전 측정·최종 집계가 끝나기 전에도
핵심 결과를 `VERIFYING`으로 표시한다. 최종 집계 후 텍스트·JSON·HTML을 저장한다.

```text
<평가 폴더>/assessment_reports/<UTC 시각>/summary.txt
<평가 폴더>/assessment_reports/<UTC 시각>/summary.json
<평가 폴더>/assessment_reports/<UTC 시각>/report.html
```

보고서에는 목표 PASS/FAIL/제외 수, 검증된 주 실패 유형과 변경 전후 값,
최종 목표 거리, 도구의 거절·실패 기록, 영상 경로, 변수 탐색 범위,
실행 중단 이유를 표시한다. 규칙 판정과 일치하지 않는 유형 귀속은 인정하지 않는다.
결과·protocol·decisions의 저장 해시와 자체 arm 경로를 확인한 뒤 출력한다.
HTML은 기록 문자열을 escape하고 영상은 상대 링크로 제공한다.

사람 접촉/보호구역 이벤트는 목표 결과와 별도로 표시한다. 공식 archive 검증이
완료된 측정만 집계한다. 측정 전·누락·제외는 안전/0으로 바꾸지 않는다.
목표 PASS에도 안전 이벤트가 나타날 수 있다. 안전 측정 캐시는 체크포인트
digest가 같을 때만 재사용하며, 손상·변경된 캐시는 거절한다.

상태·저장 보고서는 새 모델 실행 없이 조회할 수 있다.

```bash
uv run --no-sync python tools/run_humanoid_assessment.py status
uv run --no-sync python tools/run_humanoid_assessment.py report
# 중단 후 안전 측정이 미집계 상태이면 저장 근거만 다시 검증한다. 추가 API/GPU 실행 없음.
uv run --no-sync python tools/run_humanoid_assessment.py report --verify-safety
```

이 보고서는 **실제로 관측한 취약 장면**을 정리한다. 추론한 물리적 원인을
확정하거나,10회 결과를 일반 실패 확률·안전 인증·AFS의 통계적 우위로
해석하지 않는다. 실패 미검출도 이 범위에서의 결과이며 무결함 판정이 아니다.

## 별도 준비 명령

이미 준비한 기본 폴더에는 실행하지 않는다. 다른 새 버전을 준비할 때만 사용한다.

```bash
uv run --no-sync python tools/run_humanoid_assessment.py plan
uv run --no-sync python tools/run_humanoid_assessment.py init \
  --output-dir development/humanoid_assessment_NEW
```
