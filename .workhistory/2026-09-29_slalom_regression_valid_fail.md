# Slalom 회귀 두 번째 시도: 유효 목표 FAIL, 전체 suite는 제외 포함 완료

2026-09-29 UTC. 사용자 요청: 두 번째 회귀 결과의 상태 분석.
원본 archive를 읽고 manifest/계약/행동/유형·사용량을 재검증했다.
유료 모델·로봇 재실행, source 코드 변경, suite/예산/원본 수정은 하지 않았다.
기존 미커밋 EGL 진단 이력은 보존하고 이 이력만 추가했다.

## 실행 및 전체 상태

- Suite: `/workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928`
- 최신 report: `reports/20260929T152351_290501Z/report.html`
- 이번 archive: `attempts/attempt_00001/rollout/`
- receipt: returncode 0, wall 178.0108678038232s, interrupted null.
- read_goal_run 독립 검증: VALID / FAIL, exclusion_reason 없음.
- 종료: BUDGET_EXHAUSTED, actor episode_budget, goal_reached false.
- 시뮬레이션157.970s, accepted action10회/API10회, 반환 모델 gpt-6-luna.
- simulation budget은 None/unlimited. 120초 제한이나 HTTP timeout 종료가 아니다.
- protocol의 GR00T execution_provider=CUDAExecutionProvider.
- EGL import/실행/영상 단계가 이번에는 정상 통과했다. 설치 과정을 재실행하거나 추정하지 않았다.

suite는 총 시도2회(첫 EGL 시작 오류로 제외1 + 이번 유효FAIL1)를 소진했다.
따라서 COMPLETE_WITH_EXCLUSIONS이며 pending 없다. case comparison=INCONCLUSIVE는
유효 반복 수가 부족한 전체 비교의 결론이지 이번 로봇 실행의 목표 판정이 불명확하다는 뜻이 아니다.
동일 suite의 남은 시도는0이다. 임의로 budget을 복원하거나 제외를 지우지 않는다.

## 행동 시간선

| 호출 ID | 시뮬레이션 완료 시점(s) | 실행 | base XY(m) / 관측 |
|---|---:|---|---|
| 0 | 11.045 | plan_path([7,0]) | (0.957,-0.026), path_found |
| 1 | 27.755 | navigate_to([7,0]), 10s | (2.541,-0.116), execution_slice_ended |
| 2 | 43.955 | navigate_to([7,0]), 10s | (3.611,0.183), execution_slice_ended |
| 3 | 63.990 | navigate_to([7,0]), 10s | (4.914,-0.196), execution_slice_ended |
| 4 | 79.135 | navigate_to([7,0]), 10s | (5.114,-0.043), 두 번째 장애물 부근 진척 저하 |
| 5 | 83.290 | navigate_to([7,0]) | (5.120,-0.050), blocked_endpoint |
| 6 | 101.370 | move, vy=-0.0301, 2s | (5.153,-0.114), 남쪽으로 재배치하려는 정책 의도 |
| 7 | 114.820 | move, vy=-0.12, 2s | (5.221,-0.302), 더 남쪽으로 재배치 |
| 8 | 133.320 | navigate_to([7,0]), 10s | (5.168,-0.107), 다시 경계 부근으로 접근, 진척 부족 |
| 9 | 157.970 | move, vx=vy=0.15, 2s | (5.128,-0.378), 호출 예산 소진 |

모든 이동/재배치 결정은 저장된 로봇 정책 action이다. 평가자/AFS가 지시한 우회 경로가 아니다.
move 속도는 body-frame 명령이며 표의 남쪽 의도는 policy plan_summary 및 실제 XY 변화에 근거한다.
총 plan_path1, navigate_to6, move3, push0. 마지막 move 이후 추가 navigate 호출 예산이 없다.

## 막힌 시작점의 기하 근거

저장된 observation에 현재와 동일한 navigation_tools.plan을 오프라인 적용했다.
이는 API/물리 재실행이 아니라 deterministic grid 계산이며,
실제 navigate는 추론 대기 후 최신 base pose로 재계산하므로 관측 시점과 미세한 차이는 있다.

- 관측4: base(4.914,-0.196), path_found. obstacle_2까지 start grid cell 거리0.503866m.
- 관측5: base(5.114,-0.043), start cell(5.125,-0.025), obstacle_2까지0.3225m.
- 관측6: base(5.120,-0.050), start cell(5.125,-0.075), obstacle_2까지0.3725m.
- 내부 planner의 RADIUS=0.40m이므로 관측5/6은 start cell이 차단된다.
- 재배치 후 관측7/8/9는 다시 path_found. 관측9도 start 여유0.4225m로 작다.
- tool_004 및 tool_008 모두 goal까지 경로를 계산했지만, 실제10초 실행 구간의 진척이 작았다.

관측된 실패 양상은 경로 실행 중 여유 영역 침범 → 재계획 시작점 차단 → 재배치와 재추종 →
호출 예산 내 원래 목적지 미도달이다. 물리적 충돌/낙상이나 정적 경로의 완전한 부재로 단정하지 않는다.
왜 해당 궤적 차이가 생겼는지(추론 대기, 보행/추종 변동 등)의 개별 인과를 확정한 실험은 아니다.

## 물리·목표·사용량·영상

- 최종 base [5.1278245388,-0.3784510304,0.7439979324], goal까지1.9100434917m.
- goal [7,0], 반경0.25m, 1초 dwell 조건. 최대 기록 dwell0, 최소 sampled goal거리1.65913825m.
- state3160개, min height0.740536m, max tilt8.86444°. fall/recovery event0.
- contacts140405개는 floor–left ankle70414/right ankle69991뿐. 비지지 robot/world contact0.
- contact start/end 각각2199, 물체 XY변위1.15e-8m. 의미 있는 밀기/상자 이동 없음.
- self-collision 등 미구현 범위까지 모든 충돌이 없다고 주장하지 않는다.
- usage audit OBSERVED,10/10호출, warning/누락0. input300061/output7295.
  suite의 missing_attempts1은 첫 EGL 시도에 archive가 없었던 것. 이번 토큰 누락이 아니다.
- rollout.mp4 ffprobe: H.264,960×540,12fps,1896프레임,158.0s. GIF 없음.
- camera_009.png를 확인했고 가까운 주황색 장애물이 시야에 보인다.
  전체 MP4를 눈으로 재생 검토했다고 주장하지 않는다.

## 유형 규칙과 이전 성공 대비

저장된 taxonomy를 analyze_behavior/measure_taxonomy로 재계산해 일치함을 확인했다.
마지막5초 정체는 감지(거리 범위0.078697m, base excursion0.289797m).
하지만 충돌 없음, goal 점유 없음, blocked_endpoint는 앞선83.29초의1회이며 마지막10초 안에는 없음.
세 규칙 NOT_DETECTED, primary null/인과UNCONFIRMED다. 실제 목표FAIL이 무효라는 뜻이 아니다.
중간의 차단/회복 행동은 전체 행동 근거로 보존된다. 임계값을 이번 실패에 맞춰 즉석 변경하지 않는다.

기준선: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z`.
이전은 PASS,7API/6accepted(plan1+navigate5),82.925s,최종goal거리0.093929m.
scene XML/config,goal contract,robot resources는 동일하다.
프로토콜 차이는 source_hashes뿐이며, git commit eee90aa의 runner 변경은
fixture_obstacles provenance hash 추가3줄이다. 정책/계획기/보행 source hash는 같다.
그러나 전체 condition hash는 동일하지 않으므로 공식 동일-condition 반복 그룹으로 합치거나,
단 한 번의 PASS→FAIL을 코드 성능 퇴행·성공률50%로 확정하지 않는다.
동일 개발 장면의 단일 성공만으로 반복 신뢰도를 보장할 수 없다는 실제 관측이다.

## AFS 관점과 다음 작업

이번 실행은 기존 장면 회귀이며 AFS가 새 장면을 제안한 실험이 아니다.
새 실행 파이프라인/usage/taxonomy/MP4 생성이 live에서 연결되었다는 증거와
탐색해야 할 내비게이션 실패 양상을 얻었다. AFS Gain/4종 coverage 달성 증거는 아니다.
로봇을 임의로 수정하거나 호출 예산을 늘리기보다, 로봇 조건을 고정한 새17축 AFS campaign에서
장애물 위치·크기·통로 폭 등으로 성공 쪽 완화와 경계/대안 조건을 탐색하는 방향이 적절하다.
이 외부 회귀 결과를 frozen AFS arm history나 무료 cold-start에 조용히 넣지 않는다.
정식 반복 비교가 필요하면 원본/첫 제외를 보존한 별도 suite와 예산을 명시한다.
