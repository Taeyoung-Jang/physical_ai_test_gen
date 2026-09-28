# Luna 통로 AFS 파일럿: 초기 4회 결과와 근거 ID 검증 중단

## 요청과 점검 범위

사용자가 `run_afs_pilot.py --live --config config/behavior_afs_corridor_luna.json`
실행이 제대로 완료되었는지 확인을 요청했다. 기존 파일/SQLite를 읽기 전용으로
점검하고, 보관된 응답의 검증을 오프라인 재현했다. 이번 점검에서는 API/GPU 실행,
캠페인 재개/resolve, 소스 수정, 원본 산출물 수정, 커밋/push를 하지 않았다.
이 문서와 이력 색인만 추가했다.

캠페인: `/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z`

부분 보고서: `reports/20260928T120537_229862Z/report.html`

## 완료된 실험

`read_goal_run`으로 4개 archive의 manifest/계약/목표 판정을 재검증했다.
전부 VALID이고 저장된 EpisodeRecord와 동일했다. 반환 모델은 모두 `gpt-6-luna`다.

| attempt | arm | 목표 결과 | 종료 사유 | 최종 목표 거리(m) | API 호출 |
|---|---|---|---|---:|---:|
| 00000 | AFS | FAIL | BUDGET_EXHAUSTED | 4.362127 | 10 |
| 00001 | Random | FAIL | BUDGET_EXHAUSTED | 5.831051 | 10 |
| 00002 | AFS | FAIL | BUDGET_EXHAUSTED | 1.959904 | 10 |
| 00003 | Random | PASS | GOAL_REACHED | 0.102294 | 9 |

전부 `paired_uniform_cold_start`이며 적응형 제안으로 생성한 rollout은 아직 0회다.
00000/00001, 00002/00003은 각각 동일한 장면 파라미터를 별도로 실행한 쌍이다.
각 arm은 목표 6회 중 2회 완료, 제외 0회, 캠페인은 `NEEDS_ATTENTION`이다.
부분 FDR은 AFS 2/2, Random 1/2이나 공식 비교는 `not_comparable`,
`unequal_or_incomplete_valid_budget`, Gain=null이다. 초기 표본의 차이를 AFS 우월성으로
해석할 수 없다. 후자의 같은 장면 PASS/FAIL 차이는 반복 검증의 필요성을 보여주지만,
원인을 특정하지 않는다. Random 결과는 비교용이며 AFS 제안 입력에는 넣지 않았다.

완료된 accepted action 집계:

- 00000: plan_path 1, navigate_to 5, move 4.
- 00001: plan_path 1, navigate_to 2, move 7.
- 00002: plan_path 1, navigate_to 8, move 1.
- 00003: plan_path 1, navigate_to 7. 마지막 추론 대기 중 목표 도달; API 시도와 accepted action 수는 다를 수 있다.

밀기 action은 없었다. 이 결과를 물체 밀기 능력 검증으로 해석하지 않는다.
MP4는 각 `attempts/attempt_XXXXX/rollout/rollout.mp4`에 존재한다.
이번 점검은 구조화된 기록 검증이며 MP4를 시청한 시각 판독은 아니다.

## 정확한 중단 원인

`proposals/proposal_00000/response.json`은 status=completed, error=null이다.
요청/응답 context_sha256도 동일하다. API 키/연결/타임아웃 오류가 아니다.

`proposals/proposal_00000/error.json`:

```text
ValueError: unknown evidence reference
research_campaign._finish_proposal -> behavior_feedback.choose_probe -> behavior.validate
```

응답의 두 번째 `evidence_refs` 값에서 64자리 ID 중 한 글자 `9`가 빠졌다.

```text
입력: a34ae8cb1f146d7d0390a20d5a8c97d96e98f927e7eb09598620e6d501e60a69
응답: a34ae8cb1f146d7d0390a20d5a8c97d96e8f927e7eb09598620e6d501e60a69
```

첫 번째 참조 ID는 유효하다. 두 번째는 63자리로 허용된 evidence ID 집합에 없어서
host validation이 거부했다. 저장된 원문으로 동일 예외를 재현했다.
현재 요청 schema의 evidence_refs.items는 `type: string`만 지정하며, 제공된 ID의
enum으로 제한하지 않는다. 프롬프트는 제공된 ID 사용을 지시하지만 형식 계약에서
오타를 예방하지 못했다. 거부 자체는 근거 무결성 보호의 정상 동작이나, 요청 계약의
예방 보강이 필요한 응답 연결 문제다. Luna의 연구 추론 능력 부족으로 단정하지 않는다.

제안 내용은 corridor_width_m=3.5–4.0의 success_probe였다. 통로를 넓혀 우회 여유가
생기는지 확인하고, 폭 변경 시 상자 Y도 함께 바뀌는 coupling을 명시했다.
모든 결과가 FAIL이므로 확정 경계를 주장하지 않았고, navigation/recovery 문제가
대안 설명일 수 있다고 했다. 내용의 타당성과 실제 효과는 별도 검증 대상이다.

진단용 메모리 복사본에서만 누락된 ID를 원래 값으로 대입하고 같은 choose_probe를
실행하자 검증/선택이 통과해 폭 4.0m endpoint가 선택됐다. 이것은 다른 즉시 검증 오류가
없는지 확인한 오프라인 검사이며 승인된 제안/실행 결과가 아니다. 파일과 캠페인에는
이 대입을 저장하지 않았다.

## 비용과 다음 조치

관측 집계: 로봇 API 39회, 입력 1,104,831 / 출력 21,768 tokens.
AFS 요청 1회, 입력 23,044 / 출력 2,336 tokens. 청구 금액 추정은 하지 않았다.
이번 점검은 추가 모델 호출 비용이 없다.

현재 pending은 proposal_00000이다. 단순 resume은 같은 저장 응답을 다시 검증하므로
동일 오류로 멈춘다. 자동 재전송/Random 대체는 하지 않는 설계다.

권장 후속 구현(아직 미적용):

1. 요청 시 허용 evidence ID를 출력 schema enum에 결합하고 host 검증은 유지.
2. 거부 시 unknown/allowed ID를 명확히 기록하고 오타 재현 회귀 테스트 추가.
3. 기존 캠페인의 복구는 원본 보존, 변경/비용 감사, 고정 조건을 명시하는 별도 절차로
   설계. 임의로 response.json/SQLite/고정 코드 해시를 편집하거나 현재 원본을 덮어쓰지 않는다.
   소스를 바꾸면 기존 코드 고정 검사가 작동하므로 수정 뒤 같은 live 명령을 무조건
   재개하라고 안내하지 않는다. 새 캠페인이나 명시적 복구의 비용/비교 의미를 검토해야 한다.

이번 사용자 요청은 결과 점검이므로 위 소스/복구 구현과 추가 유료 실험은 수행하지 않았다.
