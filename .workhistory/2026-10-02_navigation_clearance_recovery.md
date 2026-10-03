# 경로 여유 추가와 제한된 로봇 내부 복구

2026-10-02 UTC. 사용자가 최근 결과 분석 후 수정을 승인했다. 보행 오차를 흡수할 계획 여유와
이미 침범한 보수적 발자국 여유에서 빠져나오는 로봇 내부 복구를 구현했다. 목표 판정·모델·
호출 예산을 바꾸지 않았다. 실제 새 GPU/API 실행은 하지 않았으며, 아래 검증은 오프라인이다.

## 수정 근거와 경계

검토한 원본은 다음 폴더다. 원본 파일·결과·캠페인 DB를 수정하지 않았다.

```text
/workspace/g1_failure/runtime/robot_goal_agent/20261002T044538_228766Z
```

이 실행은 유효 FAIL이며 목표까지 약 2.18m가 남았다. 네 navigate_to는 경로를 찾았지만,
상자 AABB까지의 거리가 반경 0.40m 아래로 살짝 내려가면 시작점을 포함하는 연결 검사가
바깥 방향도 거절했다. 첫 기록 침범은 약 0.2–4.3mm이고, 한 행동에서는 8.25초간 0 명령을
냈다. 경로점의 최소 추가 여유는 약 1.42cm였다. 비바닥 로봇 접촉·넘어짐·밀기는 없었다.
이 숫자의 상세 원본 분석은 [직전 검토 이력](2026-10-02_navigation_followup_live_result.md)에 있다.

AFS/평가기에서 경유점이나 행동 순서를 지정하지 않는다. GPT가 선택한 목표와 행동 시간을
로봇 내부 도구가 실행하며, 복구 불가 시 다음 선택권을 GPT에 돌려준다. 로봇 기술 개발을
AFS의 새로운 장기 선행 과제로 확장하지 않고 확인된 내비게이션 문제만 수정했다.

## 코드 변경

### 계획과 추종

`robot_vlm/navigation_tools.py`의 새 계약은 `clearance-recovery-v3`다.

- 기존 발자국 반경 0.40m는 유지하고, BFS 계획 반경에 보행 오차 여유 0.10m를 더했다.
- 0.05m 격자의 연결 선분도 계획 여유를 지키도록 반 셀 대각선 약 0.035m를 보수적으로 추가했다.
- 정확한 시작점·GPT 목표와 격자를 잇는 길이 최대 0.35m 연결은 원래 발자국 검사를 통과해야 한다.
  추가 여유 내부의 정확한 목표를 다른 격자점으로 바꾸지 않는다.
- 전체 경로의 반경을 자동으로 낮추는 fallback은 없다. 추가 여유 연결이 없으면
  `no_tracking_clearance`, 지도 연결이 없으면 `no_path`를 반환한다. 어느 것도 조작을 포함한
  모든 행동의 불가능성 증명이거나 그 자체로 목표 FAIL인 것은 아니다.
- 추종은 기존 0.35m 국소 lookahead와 비례 속도 구조를 유지하되 모서리 지름길에서도
  각 장애물의 시작·끝점 여유를 고려한다. 가까운 정확한 끝점 연결 외에는 계획 여유를 유지한다.

### 차단 이후의 제한된 복구

`NavigationSession`을 runner에 연결했다. 정상 추종이 차단되면 기하를 다시 읽는다.

- 보수적 여유 침범이 0.06m 이하인 경우에만 바깥 지점을 탐색한다. 실제 base/AABB 겹침이나
  더 깊은 침범은 자동 복구하지 않는다.
- 시작점에서 0.35m 이내, 끝점 여유 최소 0.515m인 선분을 찾는다. 가까운 AABB에 대한
  거리 제곱의 시작 방향 미분이 음수가 아닌 조건과 볼록성을 이용해 선분 전체의 거리가
  감소하지 않도록 한다. 다른 장애물에는 새 반경 0.40m 침범을 만들지 않는다. 바닥 경계도 검사한다.
- 선택한 방향을 현재 몸체 좌표계로 변환해 속도 최대 0.10m/s, 회전 0으로 실행한다.
  복구 중 기하와 현재 위치를 다시 검사한다. 전신 접촉 안전 보장이나 일반 동적 회피기는 아니다.
- 1초 동안 목적 복구점까지 5mm 이상의 진전이 없으면 `recovery_no_progress`로 반환한다.
  시작 대비 여유 악화 2cm 초과, 연결 무효, 시작점에서 0.35m 초과 이탈, 복구 3초 소모도 종료 조건이다.
- 여유 회복 후 같은 GPT 목표로 재계획한다. 행동당 최대 2회이며 무한 반복하지 않는다.
  경로가 다시 막히거나 계획이 불가능하면 구체적인 사유를 돌려준다.
- 모든 작업은 원래 행동 마감 시각 및 명시한 시뮬레이션 상한 안에서 수행한다.
  호출 수·목표 체류 조건·종료 후 grace를 늘리지 않는다. `plan_path`는 조회만 한다.

복구 조건과 수치는 공학적 선택이며 실제 G1 보행으로 보정된 성능 보장이 아니다.
추가 여유는 좁은 공간에서 계획 거절을 늘릴 수 있다. GPT의 별도 move/push 선택은 제한하지 않았다.

### 기록과 AFS 입력

- `navigation_context_NNN.json`: 행동 시작 위치·기하·새 follower 계약.
- `navigation_trace_NNN.json`: 원래 GPT 목표, 마감 시각, 차단/복구/재계획 사건과 기하·경로.
- `states.jsonl`: 정상 추종과 `clearance_recovery` 명령 구분. 기존 20Hz 표본 간격 유지.
- 도구 결과의 `navigation_recovery`: 횟수·시각·상태를 압축해 다음 GPT 기억에 전달.
  전체 재계획 경로는 trace에 보존하고 요청 기억에는 중복하지 않는다.
- P1/AFS `action_timeline`: 검증된 복구·재계획 횟수, 상태, 시각/사유 시간선을 선택적으로 보존.
  기존 평면 details 계약을 지키기 위해 사건 시간선은 문자열로 요약한다.
- 누락된 옛 기록에 값을 만들지 않는다. 잘못된 계측 자료는 분석 INVALID/PARTIAL이며
  유효 목표 PASS/FAIL을 바꾸거나 새 실패 유형/인과 원인으로 바꾸지 않는다.

새 모듈을 별도로 분리하지 않아 기존 프로토콜의 `navigation_tools`와 runner 소스 해시가
변경된 실행 조건을 식별한다. 기존 동결 캠페인·회귀 suite는 새 코드로 재개하지 않는다.
MP4 유지, GIF 비활성, 기본 출력 토큰 상한 생략, 암묵적 120초 상한 없음은 그대로다.

## 오프라인 검증

실제 저장 기하와 첫 차단 좌표 세 개를 읽어 다음을 확인했다.

| 행동 ID | 차단 시 base XY m | 원래 AABB 거리 m | 이상적 복구 후 재계획까지 s |
|---|---|---|---|
| 1 | 3.550750, 0.693637 | 0.397632 | 2.13 |
| 3 | 4.329533, 0.698865 | 0.399799 | 1.73 |
| 7 | 4.707281, 0.548407 | 0.395717 | 2.00 |

세 경우 모두 기존 선분 검사는 바깥 방향도 거절했다. 새 코드는 비영속도 복구 명령을
만들고 이상적 속도 적분에서 0.515m 여유 회복 후 같은 목표의 경로를 다시 찾았다.
회전 0, 90, 180도 각각을 포함한 재현 테스트는 외부 런타임에 의존하지 않는 최소 기하로도 보존했다.
이상적 속도 적분은 실제 G1 제어·마찰·균형·접촉을 검증하지 않는다.

원본 첫 navigation 기하/시작 위치에서 새 경로를 이상적으로 추종한 별도 진단은
약 36.23초 후 목표 거리 0.11976m에 도달했다. 이것은 연속 알고리즘 진단이며 10초 행동이나
10회 모델 호출을 실행한 결과가 아니다. 실제 목표 체류 성공 또는 예산 내 PASS로 세지 않는다.

추가 검사 범위는 다음과 같다.

- 깊은 침범/물체 내부/다른 장애물 쪽 복구 거절, 바닥 경계 복구, 회전 좌표 변환.
- 진전 없음·여유 악화·기하 변화·시간·거리·재계획 횟수 제한.
- CPU MuJoCo와 모의 제어기로 실제 runner의 조기 반환, 원래 행동·시뮬레이션 마감, 다음 정책 입력 전달.
- 조회 도구 비이동, 기존 수치 명령 보존, 목표 체류·예산·push 회귀, GIF 미생성.
- AFS 복구 근거 보존, 잘못된 자료 배제, 옛 자료에 가짜 측정치가 없는지 확인.

개발 중 검사는 옛 버전 문자열 기대치, 실제 기하를 관통하도록 작성된 체류 전용 모의 경로,
너무 큰 테스트 지도, 부동소수점 비교/기존 최소 3초 예산 조건 등의 테스트 가정을 드러냈다.
체류 전용 테스트는 추종기도 명시적으로 모의 처리하고 새 별도 테스트에서 실제 복구 경로를 검사했다.
또한 최초 복구 시간선 자료형이 기존 평면 `BehaviorInterval.details`와 맞지 않아 한 분석 검사가
실패했다. 중첩 사건 배열 대신 검증된 짧은 문자열로 전달하도록 수정했고 해당 6개 검사가 통과했다.
평가 조건이나 검증 기준을 완화하는 방식으로 수정하지 않았다.

전체 회귀 검증 명령은 다음과 같다. API 키·외부 호출·GPU 모델을 사용하지 않는다.
최종 결과는 **437 passed, 5 skipped, 94.30초**다. 수정한 Python 8개 파일의 Ruff 검사와
format 검사, 저장소 `git diff --check`도 통과했다. 건너뛴 테스트는 통과로 계산하지 않았다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
MUJOCO_GL=egl .venv/bin/python -m pytest tests/test_robot_navigation_recovery.py tests/test_robot_navigation_feedback.py tests/test_robot_goal_agent.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_push_dispatch.py tests/test_robot_push_integration.py tests/test_robot_push_skill.py tests/test_robot_push_alignment.py tests/test_robot_request_timing.py tests/test_robot_simulation_budget.py tests/test_robot_vlm.py tests/test_robot_vlm_failures.py tests/test_robot_debug_log.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/client/test_behavior_memory.py tests/client/test_behavior_regression.py tests/client/test_research_campaign.py tests/client/test_discovery_measures.py tests/client/test_corridor_campaign.py tests/client/test_afs_search_improvements.py tests/client/test_usage_taxonomy.py tests/client/test_afs_pilot.py -q
```

## 다음 사용자 실행

같은 장면을 새 로봇 조건으로 단독 실행한다. 최대 유료 로봇 호출 10회, AFS 호출 0회다.
이 변경 작업에서는 아래 명령을 실행하지 않았다. 키는 사용자 환경에서 관리한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00006/scene_config.json
```

시작 로그는 `NAVIGATION_FOLLOWER=clearance-recovery-v3`이어야 한다. 출력은 기존처럼
`/workspace/g1_failure/runtime/robot_goal_agent` 아래 새 시각 폴더다. 복구 이후 실제 이동,
재차 차단 여부와 이유, 목표 도착/체류, 비바닥 접촉·넘어짐을 확인한다. 결과가 성공해도
단일 실행으로 일반 보행 성능이나 AFS 우위를 주장하지 않는다.

문서 작성에는 write-page의 근거·미검증 범위 구분 원칙을 적용했다. 저장 위치는 사용자가
지정한 저장소 이력 폴더이며 외부 Page를 만들지 않았다. 커밋·push도 하지 않았다.
