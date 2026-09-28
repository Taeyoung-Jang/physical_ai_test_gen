# 재개된 AFS 파일럿: API 크레딧 소진과 비용 집계 갭

날짜: 2026-09-28 UTC.

## 요청·확인 범위

사용자가 재개 실행 결과의 확인을 요청했다. 기존 캠페인과 코드를 읽기 전용으로 점검했고,
실제 API 재호출, GPU rollout, 계정 결제/한도 변경, 코드 수정은 하지 않았다.
기존 미커밋 작업과 runtime 원본은 보존했다. OpenAI Docs 스킬로 공식 오류 분류를 확인했다.

- 캠페인: `/workspace/g1_failure/runtime/afs_benchmark/20260928T033700_667656Z`
- 이번 시도: `attempts/attempt_00001`, Random arm / seed 17 / paired_uniform_cold_start.
- 상세 자료: 해당 attempt의 `process.log`, `receipt.json`, `rollout/result.json`,
  `failure_diagnostic.json`, `decisions.jsonl`, `skill_005.json`, `terminal_state.json`, MP4.

## 종료 원인과 평가

- EGL import 오류는 이번 실행에서 재발하지 않았다. 로봇 실행·카메라 관측·영상 생성이 진행됐다.
- 실제 process wall time 393.6896887347102초, simulation duration 342.47999999976105초.
- 로봇 정책 API 요청 10회 중 앞의 9회는 모델 gpt-6-astra의 정상 응답을 수신하고 행동을 수락했다.
- 10번째 요청 `api_call_009.jsonl`은 약 1.214초 만에 HTTP 429로 거절됐다. timeout이 아니다.
- `failure_diagnostic.json`의 `api_error_type`은 `insufficient_quota`이며 메시지는
  "You have no credits remaining. Add credits to continue using the API ..."이다.
  요청 속도 제한으로 추정하지 않고 크레딧 소진으로 구분한다. 실제 계정 청구 내역은 조회하지 않았다.
- `result.json`: actor infrastructure, reason api_http_429, task_outcome INCONCLUSIVE,
  valid_execution false. 10회 호출 한도와 겹쳐도 마지막 정책 응답을 받지 못한 인프라 중단이므로
  BUDGET_EXHAUSTED에 의한 유효 FAIL로 바꾸지 않는다.
- process returncode 0은 결과/보고서 저장 정상 종료를 뜻하며 실험 성공이 아니다.
  wrapper exit 2로 추가 실행을 중단했다.
- 누적 AFS 유효 0/8, Random 유효 0/8, 제외 2회. AFS proposer 요청은 아직 0회다.

## 중단 전 로봇 행동 — 로그 기반, 영상 전체 시청 아님

장면: 상자 질량 9.700306412248787 kg, 상자 마찰 0.6551963092026677,
바닥 마찰 0.7764757098064792.

1. 목적지 (7, 0)까지 plan_path를 요청했고 정적 footprint 경로 없음 결과를 받았다.
   이는 조작 가능한 환경의 불가능성 증거가 아니다.
2. navigate_to를 네 번 사용해 상자 서쪽 접근 위치 (약 3.18~3.19, 0)로 접근했다.
3. 6번째 정책 결정에서 상자를 동쪽으로 0.19 m 미는 push_object를 선택했다.
   밀기 frame에서 실제 변위 x는 0.004008185410766868 m였다. skill reason은
   DURATION_REACHED, status failed, valid_execution true, handoff_complete/released true.
   이는 기술 목표 미달 사건이지 전체 goal FAIL 또는 중단 원인이 아니다.
4. 다시 목적지로 navigate_to를 요청한 뒤 짧은 전진 move를 두 번 선택했다.
5. 10번째 결정을 받기 전에 API 크레딧 오류로 끝났다. 마지막 base 위치는
   약 (3.4035, -0.2616, 0.7429) m, 목적지 거리 3.6060 m다.

MP4: `attempts/attempt_00001/rollout/rollout.mp4`, 12,983,969 bytes.
GIF는 생성하지 않았다. 밀기의 어려움은 후속 연구 가설이 될 수 있지만, 이 중단된 실행을
유효한 실패 anchor로 사용하거나 무거운 상자가 전체 실패의 원인이라고 단정하지 않는다.

## 관측 비용과 확인된 보완점

`decisions.jsonl`에서 성공 응답 9회의 usage를 직접 합산했다.

- 입력 229,698 tokens, 출력 11,287 tokens, 합계 240,985 tokens.
- 첫 호출 입력 7,550 → 9번째 입력 44,010 tokens.
- 이는 관측된 9응답의 토큰 수이며 실제 청구 금액/캐시 할인/실패 요청 비용/다른 앱 사용량은 알 수 없다.

`GoalPolicy.feedback()`는 최근 8개 action과 전체 execution 결과를 기억하고,
`body()`는 이 history와 현재 observation을 함께 보낸다. 실행 피드백에 상세 contact/behavior 정보가
포함되어 입력 증가와 중복 전송을 점검할 필요가 있다. 로봇에게 제공되는 정보 조건을 바꾸는
요약/압축은 새로운 실험 조건이므로 기존 캠페인 도중 몰래 적용하지 않는다.

`goal_run_reader.py`는 INCONCLUSIVE를 만났을 때 usage를 수집하는 `_trace()` 호출 전에 반환하고,
예외 경로의 safe 필드에도 token 집계를 포함하지 않는다. 따라서 이번 캠페인 보고서의
observed_input_tokens/observed_output_tokens는 원본 usage가 있음에도 null이다.
목표 성능 지표에서 제외하는 것은 맞지만, 제외된 실행의 관측 비용 집계는 별도로 보완해야 한다.
이 검토에서는 원본/보고서 재작성이나 importer 수정은 수행하지 않았다.

## 다음 조치

1. API 키가 속한 조직의 Billing에서 크레딧 잔액과 결제 상태를 확인한다.
   크레딧 소진은 단순 대기/재시도로 복구되지 않는다.
2. 비용을 검토한 후 충분한 크레딧을 확보하고 사용자가 명시적으로 기존 캠페인을 재개할 수 있다.
   중단된 episode의 마지막 프레임을 이어서 실행하는 것이 아니라 다음 독립 attempt를 수행한다.
3. 대규모 실행 전에 제외 실행 usage 집계와 로봇 입력 history 크기를 보완하는 것이 좋다.
   변경 시 고정 코드/정책 조건에 맞춰 새 캠페인을 사용한다.

공식 참고: [OpenAI 오류 코드](https://developers.openai.com/api/docs/guides/error-codes).
실제 진단은 HTTP 429만으로 추정하지 않고 로컬 메시지와 정상 9응답 증거로 확정했다.
