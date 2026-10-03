# 통로 완화 success_probe의 유효 PASS 확인

## 요청과 범위

사용자가 복구 캠페인에서 1회 실행한 `attempt_00004` 결과의 분석을 요청했다.
원본 JSON/manifest/행동 기록을 읽고, 기존 AFS 실패 2개와 새 PASS를 오프라인 비교했다.
카메라 000/002/004/008을 직접 확인했다. MP4 전체를 재생해 판독한 것은 아니다.
소스/캠페인/원본 결과를 변경하거나 새 API/GPU 실험을 시작하지 않았다.
이 작업 이력과 색인만 추가했다.

실행 폴더:
`/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery/attempts/attempt_00004`

기존 비교 원본:
`/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z/attempts/attempt_00002`

## 결과와 검증

`read_goal_run`으로 AFS 00000/00002/00004의 manifest/계약/목표 판정을 재검증했다.
각각 VALID FAIL / VALID FAIL / VALID PASS이고 condition_id가 모두
`6cd96413620ad7649522ac2a49d84ee785ea4361008fad6f0303a3f9209a3fdd`로 동일하다.

| 항목 | 이전 anchor 00002 | 새 success_probe 00004 |
|---|---:|---:|
| 통로 폭(m) | 2.841949916201414 | 4.0 |
| 목표 결과 | FAIL | PASS |
| 종료 사유 | BUDGET_EXHAUSTED | GOAL_REACHED |
| 최종 목표 거리(m) | 1.9599041634077636 | 0.09889963027994894 |
| API 시도 수 | 10 | 9 |
| simulation 시간(s) | 118.14999999996503 | 109.33499999997305 |

새 실행의 실제 process wall time은 87.59202802553773s, returncode=0,
interrupted=null이다. simulation 시간에는 inference wait가 포함되며 wall time과 다르다.
마지막 base 위치는 [6.905675465183318, 0.029732457031452265, 0.7445111886890919]m다.
목표 [7,0]에 대해 full-rate goal evaluator가 도착 판정을 내렸다.

유효한 이동 action 8개가 실행됐고 모두 navigate_to다. API 시도 9개 중 마지막은
목표 판정 종료 후 응답이 완료되어 적용되지 않았다(`pending_call.status=completed_after_termination`).
상자 밀기/점프는 실행하지 않았다. recorded tool statuses는 execution_slice_ended 7개,
target_reached 1개이며 blocked_endpoint는 없었다.

## 실제 행동

처음 목적지를 요청한 뒤 로봇 모델이 중간점 [2.0,0.75]를 선택하고, 이후 목적지 이동을
반복 요청했다. 경로는 상자의 +Y 쪽을 통과했다. AFS가 이 행동 순서를 지시한 것은 아니다.

| 관측 | sim time(s) | base XY(m) |
|---|---:|---|
| 000 | 2.005 | [0.9517,-0.0075] |
| 001 | 17.095 | [0.9213,0.3465] |
| 002 | 32.260 | [1.4022,0.7725] |
| 003 | 45.255 | [2.6861,0.7354] |
| 004 | 59.865 | [3.9769,0.7132] |
| 005 | 73.455 | [4.8543,0.2586] |
| 006 | 86.930 | [5.0095,-0.0446] |
| 007 | 99.510 | [6.1525,0.0305] |
| 008 | 109.140 | [6.8832,0.0270] |

상자 sampled net XY displacement는 약 1.00e-8m로 사실상 움직이지 않았다.
행동/상태/접촉 분석 구성 요소가 AVAILABLE이며 contact interval 1516개는 모두
clear_floor 지지 접촉이다. fall이나 비바닥 robot/world contact 사건은 기록되지 않았다.
샘플링된 최저 base height 0.74069m, 최대 tilt 9.01559도다. 이를 전신 안전성의 일반 보장이나
정량 안정 여유로 해석하지 않는다.

상자 질량 9.335359386209577kg, 상자 마찰 1.116672996420528, 바닥 마찰
0.9224795804663011, lateral fraction -0.1792382426966863은 anchor와 같다.
하지만 폭에 연동된 box Y는 -0.1471501088m → -0.2509335398m로 약 10.38cm 바뀐다.
따라서 geometry상 폭만 독립적으로 바꾸고 box Y를 고정한 인과 실험은 아니다.

## AFS 관점 해석

실패를 계속 강화하지 않고 성공 방향을 시험하려던 사용자 설계에 부합하는 실험이다.
완화 제안 → host 후보 선택 → 로봇 자율 실행 → 독립 목표 평가까지 연결되어 PASS가 나왔다.
단순 형식 복구 성공을 넘어 다음 실험의 성공 측 관측을 얻었다는 의미다.

AFS 자기 arm만 사용한 메모리에서는 corridor_width_m의 관측 bracket:

- 2.841949916201414m: 0 PASS / 1 FAIL.
- 4.0m: 1 PASS / 0 FAIL.
- 다음 boundary 슬롯의 미측정 중점: **3.420974958100707m**.
- search_state는 no_success_control에서 observed_bracket으로 전환된다.

이것은 확정 실패 경계가 아니다. 원본 Random 00003은 같은 2.84195m 장면에서도 PASS였다.
따라서 반복/행동 경로/추론 시간의 차이를 고려해야 하며, 폭이 작으면 반드시 실패한다는
단조성이나 개선의 단독 원인을 주장할 수 없다. Random 데이터는 이 관찰 설명에만 쓰고
AFS arm의 다음 후보 선택 메모리에 주입하지 않았다.

현재 전체 진행은 5/12회(제외 0), AFS 3/6회 = 2 FAIL + 1 PASS,
Random 2/6회 = 1 FAIL + 1 PASS다. READY / invocation_limit은 요청한 1회를
정상 종료하고 대기 중이라는 뜻이다. 다음 자동 순서는 Random 실험 뒤 AFS boundary 슬롯이다.
공정 비교는 아직 미완료이고, 복구본은 operator-assisted이므로 완료해도 정식 Gain 주장을
하지 않는다. 성공 측 탐색으로 AFS 부분 FDR이 내려가는 것은 설계상 허용되는 현상이다.

## 비용과 산출물

새 AFS 호출 0회, 캠페인 AFS 요청 누적 1회 그대로다. 로봇 API 시도는 39→48회다.
새 archive의 관측 decision usage는 입력 210,865 / 출력 3,219 tokens다.
이는 관측 집계이며 종료 후 응답 등 모든 실제 청구 비용의 완전한 합계라고 주장하지 않는다.

개별 보고서: 위 attempt 폴더의 `rollout/report.html`.
영상: `rollout/rollout.mp4` (3,145,707 bytes). GIF를 만들지 않았다.
run 명령은 캠페인 통합 보고서를 자동 갱신하지 않으므로 통합 보고서는 필요시 별도의
`run_afs_benchmark.py report --with-memory --campaign ...` 명령으로 새로 생성한다.
