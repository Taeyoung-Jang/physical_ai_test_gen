# 밀기 수치 수정 후 0.5 기준 장면 FAIL 검토

## 결론과 검토 범위

사용자가 실행한 `20261003T150653_133405Z`는 **VALID/FAIL/BUDGET_EXHAUSTED**다.
저장된 71개 artifact 해시가 일치한다. API·파싱·인프라 오류가 아니라, 10회 호출 안에
목표 반경 0.25m에서 연속 1초를 유지하지 못한 유효한 목표 실패다. 수정한 밀기 모듈의
해시는 실제 protocol과 일치하지만, 이번 실행에는 밀기 요청이 없어 해당 실행 경로의
물리 검증은 되지 않았다.

이번 작업은 원본 읽기, 코드 대조, 오프라인 importer/P1 분석과 문서 기록만 수행했다.
새 API·GPU·로봇 실행, 유료 재시도, 실행 코드·원본 archive·suite DB·목표 판정·예산 변경은
없다. 통로 폭 실험 중단 및 MP4만 저장하는 정책도 유지한다. write-page 스킬을 사용해
기존 `.workhistory` 형식으로 관측, 해석, 아직 실행하지 않은 제안을 구분했다.

## 원본과 조건

- 실행: `/workspace/g1_failure/runtime/robot_goal_agent/20261003T150653_133405Z`
- 보고서: 위 폴더의 `report.html`; 영상: `rollout.mp4`.
- scene 입력: `/workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite/attempts/attempt_00000/scene_config.json`.
- evidence ID: `7c158869ac21ff48abba5ac45e36bc7703a566fc1573bb21a0f7ec0b4a3b36d4`.
- 새 condition ID: `eb42efe331685d6e51813b38195d27a88f50b1da77b25bd15cd9c296b42b95aa`.
- scene ID: `e4a46b7c5f80b7631ce26a8e43b37c1a014f394acb02862148881cf0fe56f3c7`.

Luna, CUDAExecutionProvider, 10회 호출, push enabled, goal_outcome_v1,
goal_dwell_v1, clearance-recovery-v3 조건이다. 시뮬레이션 및 client 출력 토큰 상한은 없고,
HTTP read 300초/runner deadline 330초는 호출당 제한이다. 종료 320.545 시뮬레이션 초는
타임아웃이 아니다.

기존 suite의 0.5 PASS와 protocol 전체를 비교한 차이는 `source_hashes.push_skill`과
`source_hashes.push_alignment` 두 값뿐이다. scene.xml도 동일하다. 모델·장면·목표·예산·
navigation·기록된 의존성/자산 조건은 유지됐지만 로봇 소스가 바뀌었으므로 새 condition이다.
이전 PASS 2회와 이번 FAIL을 같은 조건의 성공률·혼합 사례·환경 경계로 합치지 않는다.
다른 조건의 관측이며, 한 번의 결과로 수정이 실패를 유발했다고 주장할 수 없다.

## 행동 순서

호출 번호는 사람이 읽는 1부터 시작하며 artifact의 observation_version은 0부터 시작한다.
10회 모두 HTTP 200, accepted이며 자동 재시도는 없었다. 실행된 행동은 navigate_to 5회,
plan_path 1회, move 3회, observe 1회다.

| 호출 | GPT가 선택한 행동 | 실행 결과 |
|---|---|---|
| 1 | 최종 목표 (7,0)로 navigate_to | 보수적인 footprint planner가 blocked_endpoint 반환. 그 자체로 FAIL 판정하지 않음 |
| 2 | (7,-0.4)까지 plan_path | path_found. 경로 조회는 이동 명령이 아님 |
| 3–6 | 같은 중간 지점으로 navigate_to 4회 | 중간 지점에 도착. 마지막 목표 중심 거리는 0.450767m |
| 7 | 몸체 좌표 vx=0.08, vy=0.09m/s로 2초 move | 목표 거리 0.357662m |
| 8 | 몸체 좌표 vy=0.12m/s로 2초 move | 거리 0.234220m, 반경 안. 연속 체류는 아직 0.080초 |
| 9 | observe 2초, 현재 위치 유지 의도 | 응답 대기 중 바깥으로 이동. 실행 시작 거리 0.269351m, 종료 0.271623m |
| 10 | 몸체 좌표 vy=0.06m/s로 2초 move | 종료 거리 0.256236m, 체류 0초. 호출 예산 소진 |

초반 계획 설명에 상자를 밀 가능성이 언급됐지만 실제 push_object나 request_skill은 없다.
상자 XY 최대 이동은 초기 저장 표본 대비 약 2.33e-8m다. 물체 이동 성공/실패로 해석하지 않는다.

## 목표 근처에서 무슨 일이 있었나

목표는 중심 좌표 한 점이 아니라 **중심 거리 <0.25m를 연속 1초 유지**하는 계약이다.
물리 step마다 평가하며, 20Hz 저장 표본의 최솟값으로 결과를 다시 판정하지 않는다.

- 8번째 move는 시뮬레이션 294.965초에 반경 안에서 끝났지만, 1초 체류는 완료 전이었다.
- 다음 GPT 호출은 이때의 `goal_context_008.json`을 받았다: 거리 0.234220m,
  체류 0.080초, 남은 체류 0.920초. 모델의 observe 선택은 이 관측에 대응한다.
- 추론 대기 동안 시뮬레이션은 계속 진행되며 로봇 내부의 base/yaw 위치 유지기를 사용한다.
  9번째 호출의 wall 지연은 약 6.950초, 해당 대기의 시뮬레이션 진행은 약 6.380초다.
  그 사이 반경을 출입했고 연속 체류가 재설정됐다.
- 전체 6,411개 저장 표본 중 가장 가까운 거리는 0.225689m, 최대 연속 체류 표본은
  0.390초다. 둘 다 inference_wait 구간에서 관측됐으며 full-rate 극값이라고 주장하지 않는다.
- observe 실행기는 **응답을 받은 시점의 현재 위치**를 anchor로 잡는다. 실행 시작 위치는
  이미 반경 밖이었으므로, 이 행동이 과거 관측 위치나 목표 중심으로 복귀하는 것은 아니다.
- 마지막 move도 잠깐 반경 안을 통과했으나 연속 1초를 채우지 못했다. 종료는
  (7.038407, -0.253341)m, 목표 중심 거리 0.256236m로 반경보다 약 6.236mm 바깥이다.
  마지막 저장 표본 거리는 0.257342m이며 full-rate 최종 결과와 시점이 다르다.

`validate_fresh`는 위치 차이 0.15m와 yaw 차이 0.2rad를 넘을 때 거절한다. 이 정도의 작은
경계 출입은 허용 범위 안이므로 행동이 승인된 것과 모순되지 않는다. 현재 유지기는 anchor에
대한 비례 속도를 G1에 전달하는 방식이며, 기하학적으로 좌표를 고정하거나 순간 이동시키지 않는다.
측정된 대기 중 drift와 경계 출입은 사실이지만, 한 실행만으로 정책·제어기·응답 지연 중
하나를 유일한 원인으로 확정하지 않는다.

`goal_dwell_v1`의 최종 목적지 자동 hold는 명시적으로 최종 목표를 향하는 유효 navigate_to에
적용된다. 이번 첫 최종 목표 요청은 planner가 차단했고, 이후 navigate_to는 모두 중간 목표였다.
뒤의 raw move/observe를 목표로 되돌리는 명령으로 임의 변환하지 않는다. 이번 실행에
navigate_goal_hold는 없고, 완료되지 않은 체류를 위해 호출 후 유예 시간을 추가하지 않았다.

## 접촉·영상·근거 품질

기록된 robot/world 접촉 285,068개는 모두 clear_floor다. 비바닥 접촉·넘어짐 이벤트는 없고,
저장 표본의 최소 base 높이는 0.740657m, 최대 tilt는 약 8.776도다. follower의 blocked
connector·recovery·within-action replan도 기록상 0이다. 첫 blocked_endpoint와 경로 추종 중
blocked connector는 다른 항목이다. 전신 안전성 일반 보증이나 새 실패 유형 라벨은 부여하지 않는다.

MP4는 H.264, 960×540, 12fps, 3,847프레임, 길이 320.583초이고 전체 디코딩이 오류 없이
완료됐다. 마지막 GPT 입력 카메라 이미지도 열어 보았다. 이것을 영상 전체의 육안 검토로
표현하지 않는다. GIF는 없다.

read_goal_run의 manifest 검증과 build_failure_memory/compact_evidence를 오프라인 실행했다.
states/events/actions/object_motion이 모두 AVAILABLE이며 새 조건에서 observed_failure
한 건, PASS 0/FAIL 1, 제외·중복·bracket 0이다. 행동 근거에는 마지막 move/observe 및
action-end 목표 거리·체류 정보가 포함된다. 메모리 DB 저장이나 AFS 호출은 하지 않았고,
공식 taxonomy의 새 family 검출·coverage 향상을 주장하지 않는다.

## 비용과 시간

10/10 호출의 usage가 모두 관측됐고 충돌·누락은 없다. 입력 322,709토큰, 출력 45,037토큰이다.
이는 제공자가 보고한 사용량이며 금액 청구 총액이 아니다. 새 AFS 선택 비용은 없다.

첫 요청은 157.224 wall 초와 출력 31,889토큰으로 길었다. 그래도 HTTP 200이고 설정된
deadline 이내다. 이 한 요청이 전체 출력의 약 70.8%를 차지하지만, reasoning 토큰 세부
내역이 없어 내부 원인을 단정하지 않는다. 나머지 응답 지연은 약 6.95–22.78초다.

행동 실행 구간의 시뮬레이션 시간 합은 45.875초, 전체는 320.545초다. 응답 대기 등과
실제 행동 시간을 구분해야 한다. API latency 합 297.198 wall 초는 시뮬레이션 초와 같은
시계가 아니므로 단순히 더하거나 빼서 세부 시뮬레이션 구간을 복원하지 않는다.

## 다음 제안 — 더 어렵게 만들기보다 새 조건의 완화 대조

수정이 반영됐지만 이번에는 push가 없어 물리적 효과는 미검증이다. 이번 실패를 덮어쓰거나
반경·체류·호출 예산을 완화하지 않는다. 현재 유효 실패는 AFS가 활용할 근거로 보존한다.

바로 도전 0.25를 더 어렵게 진행하기보다, 새 코드 조건을 유지하고 **기존 완화 0.75를 별도
한 번 실행해 성공 쪽 대조를 확인**하는 것을 제안한다. 원본 attempt_00001/scene_config.json과
이번 0.5 설정을 비교하면 차이는 box_lateral_fraction뿐이다. 옛 .75 PASS는 새 조건의
PASS를 대신하지 못한다. 새 .75 결과가 PASS라면 새 .5 FAIL과 단일 축 관측 구간을 검토할
수 있지만, 반복·원인·단조성은 아직 미확인이다. 실패하더라도 성공할 때까지 무제한 반복하지 않는다.

다음은 사용자 선택 후 실행할 명령이며 이번 검토에서는 실행하지 않았다. 최대 로봇 API
10회, AFS 호출 없음, 새 timestamp 출력 폴더 사용이다. 옛 suite run/next는 재개하지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite/attempts/attempt_00001/scene_config.json
```

이 기록은 이전 코드 수정 문서의 “새 조건 기준 실행 전” 상태를 갱신한다. 이전 실행과
그때의 분석은 당시 사실로 보존한다.
