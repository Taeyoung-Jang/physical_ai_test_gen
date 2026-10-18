# 성공 기준 분기 AFS 실제 탐색 결과 검토

## 결론

사용자 실행 세션 `20261018T081720_637822Z`는 유효6회 목표에 도달해 COMPLETE로
정상 종료했다. 새 장면6개에서 PASS3/FAIL3/제외0, 관측 실패율3/6=50%다. 개발 표본에서
30% 목표값은 넘었지만, 측정된 실패 유형0종·미분류 실패3개여서 공동 목표는 미달성이다.
외부 성공·실패 이력을 사용하는 개발 탐색으로 독립 평가나 Random 대비 Gain 실적은 아니다.

결과 경로:
`/workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z`

최종 보고서:
`reports/20261018T085405_730336Z/report.html`

## 동작과 분기 검증

Luna AFS6요청, 각 응답의 후보 수3/3/3/2/2/2개였다. 모든 후보가 기본 유효성·신규성
검사를 통과하여 전체 거절0, 부분 거절0이다. 이번에는 재제안 경로를 실제로 사용할
필요가 없었으므로, live 결과만으로 거절 후 재제안의 실행을 검증했다고 하지 않는다.
그 경로는 앞선 CPU/synthetic 테스트에서 검증한 기능이다.

선택6개 모두 실제 제시된 unmixed PASS 기준으로부터 정확히 한 축만 바뀌었음을
context·candidate 비교로 확인했다. 새 PASS를 다음 기준으로 활용했고, 이후 FAIL을
그대로 누적하지 않고 다시 PASS 기준으로 돌아왔다.

| 회차 | 기준 | 바꾼 축 | 전후 값 | 결과 |
|---|---|---|---|---|
| 0 | 입력 PASS | box_lateral_fraction | 1→.5 | PASS |
| 1 | 회차0 PASS | obstacle_2_lateral_fraction | .7→0 | PASS |
| 2 | 회차1 PASS | obstacle_1_lateral_fraction | .7→0 | FAIL |
| 3 | 회차0 PASS | corridor_width_m | 4→3.2m | FAIL |
| 4 | 회차1 PASS | box_lateral_fraction | .5→0 | FAIL |
| 5 | 회차1 PASS | obstacle_2_size_y_m | .5→.8m | PASS |

5개 축을 탐색했지만5개 유형이라는 뜻이 아니다. 회차3은 회차2의 첫 장애물 중앙 배치를
유지하지 않았고, 회차5도 회차4의 상자 중앙 배치를 유지하지 않았다. 성공 장면에서
누적된 조건은 유지될 수 있으며, 분기 자체가 인과적 독립성이나 재현성을 증명하지 않는다.
전 회차 로봇 조건은 `e8ec811981448476f029536ee0b49be2fcad786c53d86edc3a5ba5105813bd5b`로 같다.

## 세 실패의 실제 행동과 분류 조건

모든 FAIL은 BUDGET_EXHAUSTED이며10회 정책 호출을 소진했다. 인프라 중단이 아니라,
그 고정 로봇·호출 예산·목표 완료 계약에서 유효한 목표 미달이다.

### 회차2

plan2/navigate8회. 끝에서 두 번째 요청은 (7,-.35)로 이동해 부분 목표를 달성했으나
최종 goal 영역 밖이었다. 마지막 정확한 goal (7,0) 요청은 blocked_endpoint였다.
최종 full-rate 거리.423851m, dwell0이다. 종료5초는 stalled=true지만 최근10초의
해당 막힘은1개로 interference 규칙의2개 조건을 충족하지 않는다. 목표 영역 전체 점유도
없고 비지지 접촉0이다. 따라서 예측 obstacle_interference를 측정 유형으로 집계하지 않는다.

### 회차3

navigate5/move4/push1회. 밀기 요청은 observation_version6에서 unsupported_box_face로
거절되어 실제 밀기 성공·질량 한계 근거가 아니다. 마지막 두 번의 raw move로 목표에
접근해 최종 full-rate 거리.218747m로 반경.25m 안에 들어갔다. 그러나 dwell은
.6549999999994/1초로, 약.345초가 모자란 상태에서10호출 예산이 끝났다.
종료 뒤 추가 grace를 넣거나 PASS로 바꾸지 않는다.

종료 창이 goal 안을 포함하므로 stalled=false, 전체 목표 점유 없음, 비지지 접촉은
전체 구간11개지만 qualifying recent navigation contact는0개다. 예측 collision이
실제 충돌 유형으로 확인된 것은 아니다. 일반 contact_start 수천 개는 발·바닥 접촉도
포함하므로 충돌 실패 수로 해석하지 않는다.

### 회차4

navigate8/move2회, push 요청 없음. 마지막에서 두 번째 정확한 goal 접근은
blocked_endpoint, 마지막 raw move 후 full-rate 거리.979180m/dwell0이다.
상자가 종료 창 전체에서 목표 영역을 덮는 측정은 있지만, goal distance range.279890m로
정체 조건을 충족하지 않아 stalled=false다. 최근 blocked tool0, 비지지 접촉0이다.
따라서 현재 goal_occupied 규칙은 NOT_DETECTED다. 이 관측을 이유로 정체 조건을
즉석 삭제하거나 목표 점유의 인과성이 확인됐다고 하지 않는다.

세 FAIL 모두 human terminal exposure는 NOT_DETECTED이며, unreachable/perception은
현재 지원되지 않는다. 분류0종은 목표 실패가 없다는 뜻이 아니라, 현재 등록된 보수적
유형 규칙으로 뒷받침되는 분류가 없다는 뜻이다. 예측과 측정은 분리한다.

## 성공과 비용

PASS 회차0/1/5의 full-rate 최종 거리는 각각.214370/.245383/.245152m이며 필요한
goal-region dwell1초를 채웠다. sampled state 로그의 최대 dwell이1초보다 조금 작아도
full-rate 완료 기록이 따로 있으므로 sampled 값만으로 성공을 뒤집지 않는다.

신규 로봇57호출, 실제 실행 행동54개: 회차별8/7,9/8,10/10,10/10,10/10,10/9
(호출/행동)이다. 실행하지 않은 응답도 비용에는 포함되므로 호출 수와 실제 실행
행동 수를 같다고 세지 않는다. 모든57호출 usage가 관측되어 누락0이다.

| 비용 범위 | Input tokens | Output tokens | 호출 |
|---|---|---|---|
| 신규 로봇 | 1796453 | 128011 | 57 |
| 신규 AFS 선택 | 398599 | 26382 | 6 |
| 입력 로봇 이력 | 1281340 | 107606 | 43 |

신규 합계는2195052 input/154393 output tokens다. 과거 AFS 선택 비용은 로봇
아카이브에 없으므로 unknown 상태를 유지한다. 실제 금액이나 전체 과거 비용은 추정하지 않는다.
선택 wall318.923초와 rollout wall1311.239초는 실행 로그 관측치로, 개발 준비·보고서
생성까지 포함한 전체 wall이나 실제 걷기 시간과 같지 않다.

## 무결성과 영상

선언된 신규 rollout artifact436개와 최종 보고서 artifact460개 해시가 모두 일치했다.
제안 context/request/response18개 해시와6개 PASS 기준 한 축 분기도 확인했다.
MP4 6개를 ffmpeg로 끝까지 디코딩했고 GIF0개다. 로봇 영상은 각
`attempts/attempt_0000N/rollout/rollout.mp4`에 있으며 보고서에서 연결된다.

## 다음 작업 판단

유효6회 목표로 COMPLETE이므로 남은 AFS2슬롯이나 최대 시도8을 채우려고 이어가지 않는다.
이 세션 결과를 보존한다. 다음 우선순위는 많은 유료 표본을 단순 추가하는 것이 아니다.

1. 기존6유형의 의미와 현재 종료 구간 규칙이 어떻게 연결되는지 검토한다. 예를 들어
   목표 전체 점유가 있으나 마지막까지 움직이는 경우, 마지막 한 번만 접근이 막힌 경우,
   goal dwell 부족 같은 근거를 각각 어떤 진단으로 기록해야 하는지 명확히 한다.
   규칙 변경은 별도의 버전·검증을 거쳐야 하며 기존0종을 숫자 맞추기로4종으로 바꾸지 않는다.
2. family-aware 후보 배분을 검토한다. 이번에는 모든 선택이 기하학적 challenge였고,
   사람 위치·질량·마찰은 선택하지 않았다. human 후보가 제안1에서 대안으로 있었지만
   선택되지 않았다. 유형 목표의 제안 유무와 실제 실행 분배를 함께 봐야 한다.
3. 정의·단위 테스트·오프라인 evidence audit을 마친 뒤 별도 예산의 실제 탐색을 준비한다.
   FDR와4종의 공동 평가를 먼저 하고, 독립 Random 상대 Gain 평가는 그 뒤다.

이번 검토에서는 코드·분류 규칙·기존 DB·아카이브·결과·예산을 변경하지 않았다.
새 API·로봇·GPU 실행, 새 세션 생성, commit/push도 없다. 문서 작성 스킬 지침에 따라
관측값과 성과 한계를 기존 작업 이력에 기록했다.
