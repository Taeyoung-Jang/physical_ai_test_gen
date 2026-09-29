# 17축 Luna AFS 파일럿 중간 결과 — 완화 탐색 실행, 로봇 응답 토큰 한도로 중단

2026-09-29 UTC. 사용자 요청: obstacles_luna_20260929 실행이 제대로 동작했는지 검토.
원본 archive/보고서/코드를 읽고 검증했다. API 재호출, 로봇 실행, 원본 결과·캠페인 예산·코드
변경은 하지 않았다. 기존 미커밋 문서를 보존하고 이 분석 기록과 이력 색인만 추가했다.

## 자료와 검증

- Campaign: `/workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929`.
- Pilot logs: `pilot_runs/20260929T155039_926096Z`.
- Report: `reports/20260929T160742_797470Z/report.html`.
- AFS 제안: `proposals/proposal_00000/response.json`.
- 선택 감사: `attempts/attempt_00004/candidate.json`.
- 제외 진단: `attempts/attempt_00005/rollout/failure_diagnostic.json`, `api_call_008.jsonl`.
- 6개 archive를 read_goal_run으로 독립 재검증했다. manifest 파일 수는 차례대로
  49/52/53/52/51/49개이며 해시·계약·목표 판정·사용량 검증이 통과했다.
  재계산한 EpisodeRecord는 별도 후처리 taxonomy/attribution 필드를 제외하고 저장된 보고서와 모두 일치했다.
- 첫 cold start 쌍 00000/00001, 두 번째 쌍 00002/00003의 scene_config와 XML은 각각 byte-identical.
- 모든 protocol에 CUDAExecutionProvider, 로봇 응답 상한 4096이 기록돼 있다.

## 회차별 결과

| Attempt | 방법/선택 | 목표 결과 | 종료 사유 | 최종 목표 거리(m) | API 호출 |
|---|---|---|---|---:|---:|
| 00000 | AFS cold start | VALID FAIL | BUDGET_EXHAUSTED | 4.841608 | 10 |
| 00001 | Random cold start | VALID FAIL | BUDGET_EXHAUSTED | 2.911756 | 10 |
| 00002 | AFS cold start | VALID FAIL | BUDGET_EXHAUSTED | 4.021568 | 10 |
| 00003 | Random cold start | VALID FAIL | BUDGET_EXHAUSTED | 3.195743 | 10 |
| 00004 | AFS success_probe | VALID FAIL | BUDGET_EXHAUSTED | 2.172864 | 10 |
| 00005 | Random uniform | INCONCLUSIVE | api_incomplete_response | 5.457902 (중단 시) | 9 |

00005의 거리는 중단 상태의 진단값이지 유효 목표 실패의 측정값이 아니다.
5개 유효 FAIL은 모두 고정된 10회 호출 예산 내 목표 미달이며, 시간 제한/낙상/접촉 가드 종료가 아니다.
유효 실행의 event_counts에 fall/recovery가 없고 push action도 없다. 밀기를 허용했지만
정책이 이번 실행들에서는 plan_path/navigate_to/move만 선택했다.

## AFS가 실제로 바꾼 조건과 행동 근거

AFS는 자신의 cold start 2개를 읽고 success_probe 공간 2개를 제안했다.
첫 번째는 corridor_width_m 3.3–4.0, 두 번째는 box_lateral_fraction 0.35–0.85였다.
호스트는 우선순위와 제안 순서를 적용해 첫 공간의 4.0m endpoint 하나를 선택했다.
제안 공간 전체나 두 번째 공간을 실행한 것은 아니다.

- Anchor: attempt_00002, evidence df1f459ebafe98616ff08a3c96289d7f8c83199d63f8c7d258029ee2f84fc524.
- 새 실행: attempt_00004, evidence d9954bba38e1b6a3c340c502698e645e696e3332f4d50d157260cb31916cd2e6.
- 파라미터 차이는 통로 폭 하나: 2.8419499162 → 4.0m. 질량 9.3353593862kg 등 다른 16축은 동일.
- 단, lateral fraction 파라미터화 때문에 폭 변경은 상자와 장애물의 실제 Y도 바꾼다.
  상자 Y는 약 −0.14715 → −0.250934m. 독립적인 벽 이동만의 인과 실험은 아니다.
- LLM의 가설은 여유 공간을 늘려 우회 가능성을 시험하는 것이며, 무게를 계속 늘리는 공격이 아니다.
  정책/예산의 한계일 수 있다는 대안과 반증 관측도 함께 제시했다.
- request의 evidence enum과 선택 감사는 AFS 자체 cold start 두 개만 가리킨다.
  Random/외부 slalom 회귀를 무료 warm history로 넣지 않았다.

Anchor의 최초 목표 경로 요청은 no_path였다. 북쪽으로 접근하고, 목표 재계획도 no_path를
받은 뒤 상자 서쪽 밀기 접근점으로 이동했다. 실제 push는 실행하지 못하고
최종 base (2.98090, −0.14081), 목표 거리 4.021568m에서 호출 예산이 끝났다.
기록된 북벽 손 접촉 sample은 middle 234개/index 52개, 최대 접촉점 법선력 각각
14.1032/2.89685N이다. sample 수를 독립 접촉 사건 수로 해석하지 않는다.

4m 완화 장면의 최초 목표 계획은 path_found였으며 저장된 8개 plan/navigation 결과 모두
경로를 찾았다. 로봇은 두 번 방향을 조정하고 북쪽으로 우회하다 중앙 상자 뒤로 진척했다.
2 plan_path + 6 navigate_to + 2 move를 선택했고, 마지막 두 navigate는 모두 실행 구간 만료였다.
최종 base (4.83085, 0.12705), 목표 거리 2.172864m. 비바닥 robot/world 접촉 기록은 없다.

이전보다 목표 잔여 거리가 1.848704m 줄었다(result.json terminal 값 기준).
보고서 search_diagnostics의 1.852111m은 마지막 sampled state 기준이라 약간 다르다.
이는 여유 공간 관련 관측이 달라지고 더 진척한 1회 사례이지, 성공/PASS나 인과적 개선 확정이 아니다.
success_probe는 실험의 목적 이름이지 결과 PASS를 의미하지 않는다.
두 회차 모두 FAIL이므로 성공/실패 경계는 아직 관측되지 않았다.

## 마지막 중단의 직접 원인

attempt_00005의 observation_version 8, 즉 9번째 로봇 호출에서 발생했다.

- 요청: gpt-6-luna, reasoning effort high, max_output_tokens 4096.
- HTTP 200, 응답 수신 완료. elapsed_wall_s 41.33697286, read timeout 300초.
- 응답 상태는 미완성, incomplete_reason=max_output_tokens.
- 오류 코드 api_incomplete_response, output_tokens=4096, input_tokens=41027.
- 앞선 action 8개는 승인/실행됐고 9번째는 완성된 행동을 받지 못했다. 자동 retry 없음.
- API 키 오류·EGL 오류·타임아웃이 아니다. 시뮬레이션 154.04초가 120초를 넘은 것도 원인이 아니다.

로컬 원인 위치: robot_vlm/goal_policy.py의 GoalPolicy.body가 high/4096을 고정하며 push policy도
이를 상속한다. goal_runner.py의 protocol에 4096을 기록한다. api_transport.py는 completed가
아닌 응답을 실행하지 않고 진단을 남긴다. 잘린 응답을 행동으로 실행하지 않은 것은 올바르다.

OpenAI Docs 스킬에 따라 공식 문서를 조회했다:
https://developers.openai.com/api/docs/guides/reasoning
max_output_tokens는 보이는 답변뿐 아니라 추론 등 생성 토큰의 한도에도 적용되며,
도달 시 incomplete/max_output_tokens가 발생할 수 있다. 로컬 진단은 총량만 남겼으므로
4096 중 얼마가 추론 토큰이었는지는 단정하지 않는다. 추가 추론/출력 여유가 필요한 사례지만,
비용 우려를 고려해 한도를 무조건 크게 늘리거나 high를 몰래 낮추면 안 된다.

현재 정책은 이것을 infrastructure INCONCLUSIVE로 구분한다. 따라서 목표 미달 상태더라도
AFS의 목표 FAIL 분자에 넣지 않는다. PILOT_EXIT_CODE=2는 새 제외를 발견한 운영 중단이다.
READY는 pending이 없어 동일 조건으로 재개 가능한 체크포인트라는 뜻이지 전체 실험 완료가 아니다.

## 사용량·지표·예산 해석

- Robot 총 59호출, input 1,682,472 / output 55,849 tokens. 59호출 모두 usage 관측됨.
- AFS 1요청, input 25,979 / output 2,192 tokens, wall 28.00436초.
- 마지막 미완성 응답 4,096 output도 집계에 포함됐다. 제외는 무료 실행이나 비용 삭제를 뜻하지 않는다.
- 청구액은 계산하지 않았다. 로봇의 누적 관측 input이 AFS보다 훨씬 크므로 다음 비용 개선에서도
  로봇 피드백/이력 크기를 따로 측정해야 한다. 이번 로그만으로 어떤 입력 요소가 몇 토큰인지 단정하지 않는다.
- 중간 FDR은 AFS 3/3, Random 2/2로 각각 100%지만 표본 수와 완료 예산이 다르다.
  공식 comparison=not_comparable, relative_gain=null. AFS 우월성/연구 목표 달성 증거가 아니다.
- AFS distinct_failure_patterns=3은 행동 유사도 패턴 수이지 검증된 실패 유형 3종이 아니다.
- 현재 유형 규칙으로 분류된 실패는 0, coverage는 partial/unknown, 관측 하한 0/6.
  물리적 실패 유형이 없다는 뜻도, 6종 전체를 측정했다는 뜻도 아니다.
- first success/bracket 및 memory brackets는 없다.

고정 max_attempts_per_arm=6, valid_budget_per_seed=6이다.
Random은 이미 3시도 중 2valid + 1excluded라 남은 3시도가 전부 유효해도 valid는 최대 5회다.
따라서 단순 재개로 원래의 각 6회 유효 비교를 완료할 수 없다. 이 설정은 제외 여유가 없다는
한계를 드러냈다. 남은 AFS 3시도/Random 3시도는 추가 관측에는 쓸 수 있지만 완결 비교를 약속할 수 없다.
기존 제외를 삭제/실패 재분류하거나 frozen budget을 변경하지 않았다.

## 영상과 다음 조치 제안

모든 6회에 nonempty rollout.mp4가 있고 GIF는 없다. 대표 attempt_00004 MP4는
ffprobe에서 H.264, 960×540, 1483프레임, 123.583333초로 확인했다.
이번 검토는 JSON/시간선/접촉 및 영상 파일 무결성·메타데이터에 근거하며 전체 영상을 재생했다고 주장하지 않는다.

다음은 코드 수정/유료 재실행 요청을 받으면 수행할 범위다:

1. 로봇의 응답 토큰/추론 설정을 비용 상한과 함께 명시적으로 설정·고정·기록할 수 있게 검토.
   잘린 응답 제외 원칙과 자동 유료 재전송 금지는 유지. 변경은 별도 robot condition이다.
2. 적은 승인된 예산으로 설정을 점검한 뒤, 제외 여유를 명시한 별도 새 캠페인 구성.
   동일 유효 횟수 비교/콜드 스타트/반복 비용 원칙은 유지하고 최대 시도·비용 상한을 다시 공개한다.
3. 본 캠페인은 원본을 보존한 부분 결과로 남긴다. 중간에 모델/토큰/프롬프트를 바꿔 재개하거나
   실패를 더 얻으려고 목표/호출 예산을 바꾸지 않는다. 성공 쪽 탐색과 관측 경계 검증을 계속 우선한다.
