# Luna 넓은 통로 실험 분석 — 실행은 유효, 목표 도달은 실패

2026-09-28 UTC. 사용자 제공 실행 결과의 읽기 전용 분석이다.
새 API/GPU 실행, 코드 수정, 원본 결과 재분류, commit/push는 하지 않았다.
이 기록과 작업 이력 인덱스, AGENTS의 검증 범위만 갱신했다.

## 입력과 검증 방법

- 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T093634_165692Z`
- 명령: `uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --scene-config config/scenes/corridor_wide.json`
- `read_goal_run(RunInput(..., method="unassigned"))`로 manifest/계약/상태/호출 예산을 재검사했다. 개발 실행을 AFS 또는 Random arm에 임의 귀속하지 않았다.
- manifest의 52개 산출물 검증 통과, importer `VALID`, `task_outcome=FAIL`, 제외 사유 없음.
- `_scene_parameters`로 설정과 실제 XML을 대조: `clear-path-corridor-v2`, 폭4m, 상자 중앙, 질량2kg, 상자 마찰0.5, 바닥 마찰0.8. 경고 없음.
- runner, policy, push_policy, navigation_tools, fixture, scene_config의 현재 소스 SHA256이 실행 시 protocol 기록과 일치했다.
- decisions, observation, states, events, tool, terminal_state, protocol, result를 읽었다. 저장된 관측/상태에 내부 계획기를 오프라인 적용했다. 물리 재실행은 하지 않았다.
- `camera_000.png`, `camera_009.png`를 확인했다. MP4는 ffprobe로 컨테이너/스트림을 확인했으며 전체 영상을 재생해 본 것은 아니다.

## 실행 조건과 결과

| 항목 | 관측값 |
|---|---|
| 요청 및 응답 모델 | gpt-6-luna (기록된 응답 10/10) |
| 보행 backend | CUDAExecutionProvider |
| 제어 조건 | arm_ik_gait_push_align_v4 |
| 목표 | base XY가 `[7, 0]`의 0.25m 이내에서 1초 유지 |
| 예산 | 정책10회; 시뮬레이션 시간 상한 없음 |
| 결과 | 유효한 목표 FAIL / BUDGET_EXHAUSTED |
| API/정책 행동 | 10회 응답, 10회 accepted, error_diagnostic=null |
| 행동 구성 | navigate_to 8회, plan_path 1회, move 1회, push_object 0회 |
| 최종 base XY | `[4.045211, 0.921586]` |
| 최종 목표 거리 | 3.095173m |
| 기록 상태 중 최소 목표 거리 | 3.073054m |
| 시뮬레이션 시간 | 151.25초 |
| 최저 기록 base 높이 / 최대 기록 기울기 | 0.738327m / 8.929735도 |
| 이벤트 | contact_start 2102, contact_end 2102; 전부 양쪽 발목/발 geom과 바닥 |
| 낙상 / 상자·벽 접촉 이벤트 | 기록 없음 |

이번 실패는 timeout, schema 오류, 인프라 중단, 접촉 강제 종료가 아니다.
선언된 10회 안에 원래 목표를 달성하지 못했으므로 goal_outcome_v1의 FAIL 판정이 맞다.
밀기를 허용했지만 Luna는 우회와 회복 이동을 선택했다. 상자를 못 밀어서 실패한 실험이 아니다.
이 한 회는 AFS가 생성한 장면도, AFS/Random 성능 비교도 아니다.

## 행동 시간선

호출 번호는 사용자 이해를 위해 1부터 표기한다. 원본 observation_version은 0부터다.

| 호출 | 선택 / 실행 결과 | 실행 후 base XY (m) |
|---|---|---|
| 1–3 | 목표로 navigate_to; 내부 경로의 북쪽 우회 구간 추종 | 3회 후 `[2.493, 0.955]` |
| 4 | 여유 확보를 위해 `[3, 1.3]` 요청; 8초 slice 종료 | `[2.442, 1.305]` |
| 5 | 상자 북쪽으로 `[5.2, 1.3]` 요청; 8초 slice 종료 | `[3.329, 1.310]` |
| 6 | 목표 `[7, 0]`로 재계획; 경로가 다시 상자 가까이 내려감 | `[3.409, 0.873]` |
| 7 | plan_path가 blocked_endpoint 반환 | `[3.397, 0.839]` |
| 8 | 뒤/왼쪽 body velocity `[-0.2, 0.15, 0]`로 2초 회복 이동 | `[3.206, 1.109]` |
| 9 | 목표로 경로를 다시 찾고 8초 이동 | `[4.043, 0.958]` |
| 10 | 더 넓은 우회를 위해 `[5.4, 1.35]` 요청; blocked_endpoint | `[4.045, 0.922]` |

Luna가 동일 명령만 반복한 것은 아니다. 중간 목표를 변경했고, 계획기의 거부를 읽고
직접 후퇴/측방 이동을 선택해 한 번 경로를 복구했다. 다만 전체 이동을 끝내지 못했다.

## 확인한 병목: 정적 경로와 실제 보행 추종 사이의 여유 부족

`robot_vlm/navigation_tools.py`의 계획기는 5cm grid의 BFS, 반경0.40m이다.
상자 표면에서 base 중심까지 0.40m를 확보하는 정적 지도이며 전신 충돌 증명이 아니다.
북쪽 상자 면은 Y=0.55m라서 X가 상자 구간 안일 때 중심의 북쪽 경계는 약 Y=0.95m다.
상자–북쪽 벽 사이 실제 폭은 1.45m이며 정적 우회 경로는 존재한다.

1. BFS는 경로 길이를 줄이지만 여유 공간의 중앙을 선호하거나 보행 오차를 비용에 넣지 않는다.
   6번째 호출의 새 경로는 `(3.325, 1.325)`에서 Y=0.975 부근으로 내려간다.
   Luna가 직전에 선택한 넓은 Y=1.3 경로를 목표 재지정 후 계속 유지하는 구조가 아니다.
2. 추종기는 8cm 이내 waypoint를 제거하고, 전진 최대0.20m/s 및 yaw 최대0.4rad/s를 명령한다.
   lookahead/횡오차 안정화/실행 중 clearance 검사나 blocked-start 탈출을 이 함수에서 제공하지 않는다.
   따라서 정적으로 통과 가능한 점 목록이 실제 추종 여유를 보장하지 않는다.
3. 실제 기록에서 6번째 navigate 구간의 base–상자 AABB 최소 거리는 약0.37668m,
   9번째 구간은 약0.34036m로 계획기의0.40m 기준을 넘어서 안쪽으로 들어갔다.
   해당 계획 경로 점들의 최소 거리는 약0.41382m다. 이는 물리 접촉이나 전신 안전 판정이
   아니라, 같은 XY 장애물/반경 가정에서 계획과 추종을 비교한 진단값이다.
4. 7번째 호출은 기록된 관측 위치를 넣어도 blocked_endpoint가 재현된다.
   목표가 막혔다는 뜻이 아니라 이 경우 현재 위치가 inflated obstacle 안으로 분류된다.
5. 10번째 호출의 관측 시점 위치에서는 `[5.4, 1.35]` 경로가 있다. 그러나 실행 시 저장된
   tool 결과는 blocked_endpoint다. 주변 상태를 재검사하면 150.905초(Y=0.946186)는 blocked,
   150.955초(Y=0.950226)와151.005초(Y=0.951008)는 path_found,
   151.055초(Y=0.948802)는 blocked다. 대기 중 작은 자세 흔들림만으로 분류가 바뀐다.
   상태는50ms 간격이므로 정확한 planner 호출 순간의 자세를 재구성했다고 주장하지 않는다.

따라서 주요 개선 대상은 로봇 내부의 경로 생성–추종–회복 연결이다.
단일 기록으로 Luna 자체의 성능 부족 또는 특정 코드 변경의 성공을 단정하지 않는다.
실행 시간이 151초인 데 비해 sampled phase 합산으로 실제 navigate는 약56.25초,
move2초, inference_wait90.75초다. API 지연 합계와 simulation 시간은 서로 다른 시계다.
기록된 base 누적 경로 길이18.197m에는 제자리 보행/좌우 흔들림이 포함되므로
18m를 목적지 방향으로 전진했다고 해석하면 안 된다.

## 비용 및 미디어

- 응답 usage 합계: input315,307 / output7,780 tokens. 전체 청구금액 추정은 하지 않았다.
- 첫 호출 입력7,121에서 9번째48,758, 마지막47,745로 증가했다.
- `GoalPolicy.feedback`는 최근8개 행동의 전체 result를 보관한다. 여기에는 촘촘한 경로 점과
  반복적인 발–바닥 접촉 feedback이 포함되고 다음 요청 history로 다시 전달된다.
  가격 모델 변경과 별도로 입력 압축을 검토할 근거다. 토큰 항목별 기여율은 아직 측정하지 않았다.
- 10개 `latency_s` 합계98.025초, 범위 약5.08–15.98초. timeout 기록 없음.
- `rollout.mp4`: H.264, 960×540, 1815 frames, 151.25초, 3,857,074bytes.
- GIF는 만들지 않는 기존 설정을 유지한다. 원본 영상/로그는 수정하지 않았다.

## 권장 다음 작업 (이번에는 구현하지 않음)

1. 로봇 내부 navigation 개선: tracking-aware clearance/경로 평활화 또는 lookahead,
   실행 중 추종 오차 점검, 명시적인 blocked-start 회복 feedback을 검토한다.
   장애물 통과를 위해 반경/평가 기준을 임의 완화하거나 위치를 순간 이동시키지 않는다.
2. LLM 입력은 현재 상태·계획 요약·실행 성과·중요 사건 위주로 압축하고 전체 근거는 별도
   로그에 보존한다. 입력 크기를 계측하고 기존과 다른 정책 조건임을 기록한다.
3. 코드/조건이 바뀌면 새 실행으로 넓은 통로 성공 대조를 먼저 확인한다. 호출 예산을
   무조건 늘리거나 전체 AFS 캠페인을 즉시 실행하지 않는다. 비교 시 로봇 조건을 동결한다.

이 기록은 탐색 대상 로봇의 약점을 관측한 자료다. AFS의 실패 탐색 성능, PASS/FAIL 경계,
실패 유형 coverage 또는 Luna/Astra 우열의 입증으로 사용하지 않는다.
