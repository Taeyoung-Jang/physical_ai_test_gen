# 도착 처리 옵션 적용 후 이동 정체 결과 분석

2026-10-02 UTC. 사용자가 단독 Luna 실험의 FAIL 및 BUDGET_EXHAUSTED 결과를 공유했다.
원본 기록·코드·스키마를 읽기 전용으로 검토했다. 새 실험, 유료 호출, 실행 코드 수정,
원본 결과 재분류는 하지 않았다. 기존 작업 트리의 구현 변경은 그대로 보존했다.

결론은 **유효한 목표 실패지만, 이번에는 목표에 접근하지 못해 새 체류 유지 동작은
검증하지 못했다**는 것이다. 경로 추종 정체 뒤 설명과 다른 0속도 명령이 반복됐다.
이를 물체 무게·마찰 때문에 발생한 실패로 해석할 근거는 없다.

## 원본과 검증

- 새 실행: `/workspace/g1_failure/runtime/robot_goal_agent/20261002T033720_696599Z`.
- 비교 장면: `/workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00006/rollout`.
- 새 manifest의 58개 파일 해시 및 목표·조건·사용량 계약을 read_goal_run으로 검증했다.
- 결과는 VALID / FAIL, 종료 actor는 episode_budget, reason은 BUDGET_EXHAUSTED다.
- 10개 API 요청 모두 HTTP 200 및 completed, 10개 행동 승인, 오류 진단 null이다.
- 프로토콜은 gpt-6-luna, CUDAExecutionProvider, goal_outcome_v1,
  navigation completion goal_dwell_v1, 호출 최대 10, 시뮬레이션 상한 없음이다.
- 최종 sim 134.97499999995초, 위치 `[0.8114867, 0.9930965]`, 목표 `[7, 0]`이다.
- 최종 목표 거리 6.26768994m, sampled 최소 거리 5.88073120m, 체류 최대 0초다.
- 발과 바닥 접촉만 기록됐다. 비바닥 robot-world contact 0, fall event 0이다.
  최소 base 높이 0.74034m, 최대 sampled tilt 8.77635도다.
- push 실행은 없었다. enable-push는 선택 가능한 기능이지 사용 의무가 아니다.

## 로봇 행동 순서

아래 호출 번호는 사용자에게 익숙한 1부터 시작한다. 아카이브 observation_version은 0부터다.

| 호출 | 선택한 행동 | 저장된 결과 |
|---|---|---|
| 1 | plan_path `[7,0]` | path_found |
| 2 | navigate_to `[7,0]`, 10초 | path_found 후 실행 시간 소진, 위치 약 `[0.928,0.167]` |
| 3 | navigate_to `[2,0.75]`, 10초 | 위치 약 `[1.073,0.863]`, 목표점 미도달 |
| 4 | navigate_to `[2.7,1]`, 10초 | 위치 약 `[1.004,1.049]`, 목표점 미도달 |
| 5 | move, yaw rate 0.4, 2초 | 방향 전환 실행 |
| 6부터 10 | move, 설명은 옆으로 또는 동쪽으로 이동 | vx·vy·yaw rate 모두 0 |

모든 navigation 요청은 경로를 찾았다. no_path 또는 blocked_endpoint로 중단된 것은 아니다.
세 구간의 sampled yaw 명령은 각각 100%, 86.5%, 100%가 크기 0.4rad/s의 제한에 걸려 있었다.
첫째·셋째 구간의 명령 전진 속도 최대는 각각 약 0.0391m/s, 0.0539m/s다.
이는 회전 중심의 추종 정체를 보여주지만 waypoint 한 점의 정확한 내부 추적 상태나
물리적인 원인을 모두 입증한 기록은 아니다. 전체 base X는 약 0.791부터 1.198m 사이였다.

후반의 저장된 명령은 다음 형태다.

```json
{"action": "move", "vx_mps": 0.0, "vy_mps": 0.0, "yaw_rate_rps": 0.0}
```

6부터 10번째 plan_summary는 측면 이동 또는 양의 body-left 속도를 이야기한다.
마지막 설명은 이전 명령이 0이었음을 인지했다고 적었지만 수치 필드는 다시 모두 0이었다.
이 5개 행동의 states.jsonl command도 `[0,0,0]`이다. 자세·보행 잔류 운동은 있을 수 있으나
실제로 원하는 측면 이동 속도가 전달된 것은 아니다.

## 명령 변환 검사와 확정 범위

실행 당시의 observation contract, goal/push policy, wire_contract, runner,
navigation_tools, api_transport 해시가 현재 분석 코드와 모두 일치한다.
Move 스키마는 vx -0.2부터0.3, vy -0.15부터0.15, yaw rate -0.4부터0.4를 허용한다.
저장 행동의 vy를 0.1로 바꾼 메모리 내 입력을 PushEnvelope에 넣으면 move와 vy=0.1이
그대로 보존됨을 6개 입력으로 확인했다. API는 호출하지 않았다.
runner는 move의 세 수치 필드를 그대로 저수준 명령으로 전달한다.

따라서 현재 확인된 것은 **정책 설명과 승인된 수치 행동의 불일치**다.
스키마가 이동 속도를 무조건 0으로 제한하거나 로컬 파서가 0으로 덮는 문제는 확인되지 않았다.
성공 응답의 원문은 저장하지 않고 응답 해시·정규화 행동을 저장하는 구조다.
미보존 원문까지 직접 대조했다고 주장하거나 모델 내부의 원인을 단정하지 않는다.
설명만 읽어 평가기가 임의로 속도를 바꾸거나 유료 재질문을 추가하지 않았다.

## 새 체류 유지 기능의 실제 적용 범위

최종 목표 대상의 두 번째 호출은 goal_dwell_enabled_for_target=true였으나
first_target_arrival_s=null, hold_simulation_s=0이다.
다음 두 navigation은 중간 목표여서 해당 flag가 false였고 hold 시간도 0이다.
states에 navigate_goal_hold 구간은 없으며 terminal 진단의
budget_ended_during_goal_dwell=false다. 따라서 설정·진단·저장은 실제 실행에서 확인됐지만
최종 도착 후 1초 유지 기능의 물리 실행 증거는 이번에도 없다.
0.775초에서 중단됐던 과거 실패와 이번 실패를 같은 체류시간 문제로 요약하면 안 된다.

## 이전 근접 실패와의 비교

scene config와 scene.xml은 byte 수준에서 동일하고, robot resources도 같다.
처음 observation의 base 좌표도 동일하다. 비교 프로토콜에서 다른 최상위 키는
navigation_completion, prompt_version, source_hashes다.
원래 추종기 코드의 해시는 동일하며, 정책 컨텍스트와 도착 처리는 새 버전이다.

| 항목 | 이전 근접 실패 | 이번 실행 |
|---|---:|---:|
| 최종 목표 거리 | 0.11937m | 6.26769m |
| 행동 | plan 1회와 navigate 9회 | plan 1회와 navigate 3회 및 move 6회 |
| 목표 체류 | 약 0.775초 | 0초 |
| 결과 | FAIL | FAIL |

GPT의 중간 목표 선택과 호출 지연도 달라졌다. 예를 들어 세 번째 목표는 이전 `[1.8,0.75]`,
이번 `[2,0.75]`였다. 추론 대기가 물리 시간에 포함되므로 지연 차이도 상태에 영향을 줄 수 있다.
이번 성능 차이를 체류 유지 분기의 실행 효과나 동일 조건 반복 분산으로 단정하지 않는다.
이 단독 실행을 기존 완료 캠페인의 AFS/Random 집계에 추가하지 않는다.

## 유형과 AFS 해석

P1 행동 근거는 states/events/actions/object_motion 모두 AVAILABLE로 읽혔다.
goal-behavior-v1의 세 구현 규칙은 모두 NOT_DETECTED, 나머지 세 종류는 UNSUPPORTED다.
마지막 5초 정체는 관측됐지만 비바닥 접촉, 최근 blocked planning, 목표 점유 근거가 없었다.
새 장애물 간섭·collision·perception 유형으로 임의 분류하거나 coverage를 늘리지 않는다.

사용자의 목표 기반 정의로는 평가 대상 로봇 시스템의 유효 실패다.
그러나 이번 행동은 상자 밀기나 장애물 접촉 단계에 도달하지 않았으므로,
상자를 무겁게 하거나 마찰을 바꾸는 것이 원인에 맞는 다음 탐색이라고 단정할 수 없다.
AFS에는 이동 정체와 수치 행동의 무효성이라는 관측 근거를 보존하는 것이 우선이다.

## 비용과 영상

- 로봇 API 10회, 입력 300977토큰, 출력 7633토큰. usage 누락 0, conflicts 0이다.
- 이번 실행에 별도 AFS API 호출은 없다. 청구 금액은 계산하지 않았다.
- rollout.mp4는 H.264, 960×540, 1620프레임, 135초, 3329555bytes다.
- GIF는 없다. 메타데이터와 해시를 확인했으며 전체 영상 재생을 완료했다고 주장하지 않는다.

## 다음 우선순위

호출 예산 확대나 반복적인 유료 재실행에 앞서, 기존 로그를 이용한 좁은 진단을 권한다.
첫째는 가까운 waypoint 추종 중 회전 정체의 재현과 waypoint 진행 상태 계측,
둘째는 이동 의도 설명과 실제 수치 명령 불일치의 로봇 내부 피드백이다.
어떤 경우에도 평가기가 특정 이동 방향을 대신 정하거나 0속도 명령을 임의 보정하지 않는다.
실행기·피드백을 바꾸면 새 로봇 조건으로 기록하고, 동일 조건의 후속 AFS 표본만 묶는다.
이 검토에서는 코드 수정·새 실험·commit/push를 하지 않았다.
