# 17축 Luna AFS 완료 결과: 6+6 유효 실행, 관측 Gain 20%, 근접 도달 FAIL 감사

2026-09-29 UTC. 사용자 요청: 출력 토큰 기본 상한 제거 후 새 캠페인 결과 분석.
이번 작업은 원본 read-only 검증과 문서 기록이다. 코드/평가기/예산/원본 SQLite를 변경하거나,
API·로봇을 재실행하지 않았다. 시작 시 git worktree는 clean이었다.

## 원본 및 무결성

- Campaign: `/workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z`.
- Report: `reports/20260929T170613_203348Z/report.html`.
- Pilot: `pilot_runs/20260929T163136_846775Z`.
- 완료: COMPLETE, reason/pending/recovery null, PILOT_EXIT_CODE=0.
- AFS/Random 각 6시도·6유효, 전체 12유효, 제외 0, AFS 요청 2, 로봇 요청 120.
- 12개 원본을 read_goal_run으로 다시 읽어 manifest/계약/목표 판정/사용량을 검증했다.
  각 manifest 파일 수: 48,47,55,55,53,50,53,53,50,53,48,47.
  taxonomy/attribution 후처리 필드를 제외한 재계산 EpisodeRecord와 최종 보고서의 차이는 모두 없었다.
- cold start 쌍 00000/00001 및 00002/00003의 scene_config/XML byte 일치를 확인했다.
  반복 00010은 AFS cold start 00000과 동일 config/XML이다.
- 모든 protocol에 CUDAExecutionProvider와 null max_output_tokens_per_call이 기록됐다.
  AFS request 두 개 모두 max_output_tokens 필드가 없고 응답은 completed이다.
- 120개 로봇 호출 usage가 모두 관측됐다. 최대 output은 3425토큰(00007의 호출 ID8).
  이번에 토큰 잘림은 없었지만, 어떤 호출도 4096을 넘지 않았으므로 정상 종료를 상한 제거만의
  인과적 효과라고 주장하지 않는다. 제거된 요청 설정의 적용과 이번 실행의 완료는 확인됐다.

## 회차별 결과

| Attempt | 방법/전략 | 결과 | 최종 목표 거리(m) | sim(s) | 실제 승인 행동 |
|---|---|---|---:|---:|---|
| 00000 | AFS cold start | FAIL | 4.925005 | 146.660 | plan1/nav4/move5 |
| 00001 | Random cold start | FAIL | 4.824275 | 123.080 | plan2/nav2/move6 |
| 00002 | AFS cold start | FAIL | 3.802362 | 164.395 | plan2/nav6/push2 |
| 00003 | Random cold start | FAIL | 3.814645 | 156.015 | plan1/nav6/push3 |
| 00004 | AFS success_probe | FAIL | 2.946915 | 108.275 | plan2/nav8 |
| 00005 | Random uniform | FAIL | 5.324786 | 167.895 | plan2/nav5/move3 |
| 00006 | AFS success_probe | FAIL | 0.119367 | 140.495 | plan1/nav9 |
| 00007 | Random uniform | FAIL | 4.961049 | 214.840 | plan2/nav8 |
| 00008 | AFS independent exploration | FAIL | 5.273472 | 174.480 | plan3/nav4/move3 |
| 00009 | Random uniform | PASS | 0.098325 | 127.210 | plan1/nav8 |
| 00010 | AFS control repeat | FAIL | 4.145173 | 126.010 | plan2/nav3/move5 |
| 00011 | Random uniform | FAIL | 3.955794 | 127.675 | plan2/nav2/move6 |

모든 회차의 API 요청은 각각10회다. 00009는 마지막 요청 대기 중 goal을 달성해
승인 행동은9개이고, 종료 후 반환 응답은 pending_call.json에 executed=false로 보존했다.
11개 FAIL의 종료 사유는 모두 BUDGET_EXHAUSTED다. 낙상/회복 event는 모든 회차에서0,
낙상·접촉 가드나 timeout으로 실패 판정을 내린 회차는 없다.
이는 접촉이 전혀 없었다는 뜻은 아니다. 00002/00003에는 실제 밀기 접촉이 있었다.

## FDR/Gain/유형 지표

`.blueprint/Failure_Case_Goal.md`의 목표와 최종 metrics.json을 대조했다.

| 항목 | AFS | Random |
|---|---:|---:|
| 유효 실행 | 6 | 6 |
| 목표 FAIL / PASS | 6 / 0 | 5 / 1 |
| FDR | 100% | 83.3333% |
| 서로 다른 실패 scene | 5 | 5 |
| 동일 scene의 추가 FAIL | 1 | 0 |
| 근거 규칙으로 분류한 유형 | 장애물 간섭 1종 | 0종 |

comparison.status=measured, relative_gain=0.2, 차이16.6667 percentage points,
failure_count_difference=1, gain_target_observed=true다. `(6−5)/5=20%`이며 20 percentage points가 아니다.
본 표본에서 FDR≥30%, 상대 Gain≥20%의 점추정 목표는 관측됐다.
하지만 단일 seed17, 각6회, 실패1회 차이이고 AFS의 하나는 예산에 포함된 반복이다.
따라서 일반적/통계적 우월성, 고유 실패 장면20% 증가, 연구목표 전체 달성이라고 주장하지 않는다.
두 방법 모두 높은 FDR인 영역이어서 실패만 늘리는 지표에는 포화/비교 구분력 한계도 있다.

AFS는 서로 다른 행동 패턴6개로 보고되지만 이는 heuristic signature이며 실패 유형6종이 아니다.
분류된 장면은00004 하나다. AFS의 관측 coverage 하한은1/6, 전체 coverage는 partial/null이다.
도달불가/작업자 위험/인식 오류 규칙은 여전히 unsupported. 4/6 목표는 달성하지 않았다.
00004/00006/00009는 저장된 BehaviorEvidence를 타입 검증해 measure_taxonomy를 재계산했고,
세 경우 모두 저장된 taxonomy와 정확히 일치했다. 원본을 수정하지 않았다.

## AFS는 행동을 읽고 어떤 장면을 선택했나

두 제안 모두 AFS 자신의 arm/seed 근거만 사용했다. 첫 제안은00000/00002,
두 번째는 그 두 회차와 새00004를 포함한다. Random의 성공은 AFS history에 넣지 않았다.
두 번째 request에00004의 operational_taxonomy=obstacle_interference와 전체 bounded action timeline이
들어 있는 것을 확인했다. 따라서 관측→유형/행동 근거→다음 제안→실제 실행 연결이 확인된다.

1. 00002의 폭2.8419499162m에서00004의4.0m로 확장했다.
   다른16축 파라미터는 동일하나 lateral fraction의 정의상 상자/장애물 Y도 폭과 함께 변한다.
   상자 Y는 약−0.14715→−0.250934m. 목표 잔여 거리는3.802362→2.946915m.
   00002의 초기 목표 계획은no_path,00004는path_found로 시작했으나 후반 호출7/8/9에서
   blocked_endpoint를 반복했다. 최종 base(4.126982,0.655804), 실제 물체 접촉 없이 정체했다.
2. 00004를 anchor로00006에서 obstacle_2_lateral_fraction만0.612259→1.0으로 바꿨다.
   폭4m를 유지하며 두 번째 정적 블록을 북쪽 벽 쪽으로 옮기는 가설이다.
   로봇은 상자 북쪽을 우회해 목표 근처까지 진행했고 잔여 거리는0.119367m가 됐다.
   더 무겁게 하는 공격을 반복한 것이 아니라 두 단계의 성공 쪽 완화를 실행했다.
3. 남은 고정 슬롯에서00008은 독립 표본,00010은 초기 실패의 반복을 실행했다.
   00006의 near-goal을 반복하지 않은 것은 고정 repeat 선택 정책의 결과다.
   close-to-success 우선 반복/후속 탐색은 향후 개선 후보이며 이번 결과에 맞춰 슬롯을 소급 변경하지 않았다.

첫 proposal은2개 공간, 두 번째는3개 공간을 제안했지만 각 proposal에서 endpoint 하나만 실행됐다.
상자 측면 배치/마찰 제안은 실행되지 않았다. LLM의 설명은 가설이지 검증된 인과 설명이 아니다.
특히00004 종료 위치는 두 번째 블록보다 상자에 더 가까웠다(아래 유형 근거 참조).
두 번째 블록 변경과 정책의 매회 다른 subgoal/행동 구간 길이가 함께 관측되므로
“그 블록이 원인이었고 옮겨서 해결됐다”로 단정할 수 없다.

추가 프롬프트 점검: 두 번째 제안의 **선택되지 않은** box_lateral_fraction 설명은
폭4m의 Y 변환 배율을0.9m라고 썼다. 실제 공식은 width/2−0.60=1.4m이다.
실행기는 실제 SceneConfig 공식을 사용하며 선택 축도 달라 이번 rollout의 기하를 손상시키지 않았다.
LLM 서술의 수치 정확성은 schema/축 범위 검증만으로 보장되지 않는다는 개선 항목으로 남긴다.

## 12cm까지 도착했는데 왜 FAIL인가 — 평가 계약의 민감한 사례

00006은 “길을 끝까지 못 찾음”이나 “넘어짐”으로 요약하면 부정확하다.
고정 goal contract는 base가[7,0]의 반경0.25m 안에 **연속1초** 있어야 PASS다.

- goal 반경 진입 시점139.71999999994543s.
- 마지막 sampled state140.45499999994476s: 거리0.126058m, dwell0.735s.
- terminal140.49499999994472s: 거리0.119367m, 동일 진입 기준 dwell0.775s.
- goal까지12cm 미만이면 navigate_to 도구는 target_reached로 조기 종료한다.
- 이때 10번째 행동까지 모두 사용해 outer calls<max_calls가 종료되고,
  goal evaluator의1초 dwell에는 약0.225초가 부족한 채 BUDGET_EXHAUSTED가 된다.

00009의 Random 성공은9번째 승인 행동 후 같은 target_reached를 받았지만 호출이 하나 남았다.
10번째 요청을 기다리는 inference_wait에서 hold/physics가 계속됐고,
126.21s에 시작된 dwell이127.21s에1초가 되어 PASS로 종료됐다.
나중에 반환된10번째 행동은 실행하지 않았으며 input45511/output225 사용량은 집계했다.

따라서 이번 FAIL은 현재 사전 고정된 규약에 일치하나 **navigation 도구 완료와 task 완료의
체류시간 차이 및 마지막 호출 경계**에 민감한 사례다. 나머지 이동 실패와 같은 물리적 난도로
해석하지 않는다. 추가0.225초 유지했으면 무조건 PASS였다는 반사실도 실제 실행 없이 확정하지 않는다.
이미 완료된 결과를 PASS로 바꾸거나 dwell/마지막 행동 후 평가 시간을 소급 늘리지 않았다.
이 종료 규약은 후속 비교 전에 점검할 우선 항목이다. 변경하면 별도 조건/프로토콜로 검증해야 한다.

## 장애물 간섭 규칙의 실제 근거

00004의 마지막5초: 목표 거리 변화0.007081m, base excursion0.031002m로 정체.
마지막10초 안에 완료된 blocked_endpoint 두 개와 물체 근접 조건을 만족한다.
최종 base에서 상자까지 투영 거리0.359286m, obstacle_2까지1.056244m다.
장애물 간섭 규칙은 이 시간적/기하학적 연관성을 탐지했다. 물리적 충돌·경로 절대 불가능·
특정 장애물의 인과를 입증하지 않는다. causal_status=UNCONFIRMED를 그대로 유지했다.

## 밀기 및 Random 성공 관측

00002: push2회 중1회 alignment_out_of_range 거부,1회 실제 밀기 후 DURATION_REACHED.
기록된 접촉6.83초, 목표 상자 이동0.15m 대비 실제 net XY약0.005642m(5.6mm).
00003: push3회 중alignment_out_of_range/alignment_motion_limit 거부2회,
실제 밀기1회 DURATION_REACHED. net XY약0.005595m.
이벤트는 행동 근거이며 두 회차의 최종 FAIL은 여전히 원래 목표 미달이다.

Random PASS00009는 폭3.796596m, 상자 lateral fraction0.467249 등 별도17축 표본이다.
상자/장애물 남쪽을 plan1+nav8로 우회했으며 push 없이 목표 조건을 만족했다.
낙상/비바닥 robot-world 접촉 기록이 없다. 다른16축도 달라 폭만으로 성공을 설명하거나,
AFS00006과 같은 단일축 성공/실패 bracket으로 묶을 수 없다.
최종 memory는9개 case group, bracket0개. AFS 자체 PASS와 관측 bracket은 아직 없다.

## 비용·영상·후속 우선순위

- Robot: 120요청, input3,445,211/output118,879. 누락 호출/시도0.
- AFS: 2요청, input62,735/output4,801. 관측 wall54.2704초.
- Robot rollout wall 합계1720.0807초. API 사용량은 청구 금액으로 환산하지 않았다.
- 대부분의 입력 토큰은 로봇 측이다. 비용 개선 시 AFS 요청2개보다 로봇 관측/피드백 크기와
  종료 직전 불필요한 추론 요청을 먼저 진단할 가치가 있다. 이번 분석에서 입력을 임의로 생략하지 않았다.
- 12회 모두 MP4 파일/manifest를 확인했고 GIF0개다.
  대표00006: H.264,960×540,1686프레임,140.5초.
  PASS00009: H.264,960×540,1527프레임,127.25초.
  이번 검토는 구조화된 로그/메타데이터 분석이며 전체 영상을 직접 재생했다고 주장하지 않는다.

후속 권고는 즉시 대량 재실행이 아니다:

1. 마지막 navigate 종료와 goal dwell의 차이를 평가/로봇 실행 규약으로 명확히 감사한다.
   원본 FAIL/계약은 보존하며 새 규약이 필요하면 별도 실험 조건으로 도입한다.
2. 근접 성공00006, 관측 성공00009, 장애물 간섭00004를 별도 승인 예산의 회귀/후속 탐색 자산으로
   반복 검증하고, AFS의 close-to-success 주변 장면 탐색을 개선한다.
   Random PASS를 완료된 AFS history에 소급 주입하지 않는다. 공유 anchor를 쓸 새 설계라면 명시한다.
3. 단일20% 점추정에 멈추지 말고 고유 실패/near-goal/성공 경계/유형 범위 및 비용을 분리 평가한다.
   더 큰 다중 seed 비교는 이 조건을 고정한 후 별도 예산으로 수행한다.
