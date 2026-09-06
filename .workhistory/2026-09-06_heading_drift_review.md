# 보행 방향 편차 및 평가 코드 검토

검토일: 2026-09-06 UTC. 사용자 요청에 따른 읽기 전용 진단으로 제어기와 평가 코드는 수정하지 않았다. 이 문서만 추가했다.

## 확인 자료와 방법

- 공식 로컬 저장소: GR00T-WholeBodyControl/decoupled_wbc/sim2mujoco/scripts/run_mujoco_gear_wbc.py
- 현재 연결: scene2test/src/simulation_server/groot_locomotion.py
- 현재 평가: scene2test/src/simulation_server/worker.py
- 30초 기록: /workspace/g1_failure/runtime/server/outputs/jobs/job_4431768dcfdd4056adae0a8cc284dada/state_trajectory.jsonl
- 공식 클래스의 관측 및 quaternion 함수만 AST로 추출해 실행했다. GUI와 keyboard listener, 모델 추론은 실행하지 않았다.
- 기존 6,000개 궤적 상태 중 100개 간격의 60개에서 두 관측 함수를 비교했다. 동일한 command와 이전 action=0을 입력했으며 최대 절대 오차는 0이었다. 실제 action 전체 시계열 동등성 검증은 아니다.
- MuJoCo mj_integratePos로 90도 heading에서 local-X 각속도를 적분하여 free-joint angular velocity가 local frame임을 확인했다.

## 실제 경로 편차

| 시각 | x (m) | y (m) | heading (deg) |
|---|---:|---:|---:|
| 5초 | 1.171902 | -0.313585 | -10.967879 |
| 10초 | 2.398036 | -0.665759 | -15.181128 |
| 20초 | 4.764967 | -1.611924 | -24.236836 |
| 30초 | 6.976037 | -2.870735 | -34.703678 |

world Y 속도를 R의 body X/Y/Z 성분별로 분해해 dt=0.005로 적분했다.

- body 전진 성분 기여: -2.645865 m
- body 횡방향 성분 기여: -0.204402 m
- body 수직 성분 기여: -0.020467 m

합은 관측 횡편차와 일치한다. 약 92%가 body 전진 성분의 world Y 투영으로 설명된다. heading drift가 주된 경로 이탈 기여 요인이며 이것만으로 그 drift의 근본 원인이 특정되지는 않는다.

## 공식 예제와 일치하는 부분 및 차이

- 86차원 관측, 6-step history, action scale, PD gain, physics 0.005초, decimation=4, step 후 추론 순서는 일치한다.
- 제어 입력 각속도는 양쪽 모두 qvel[3:6]을 사용한다.
- 정책 관측에는 실제 world heading이나 경로 횡오차가 없다. rpy_cmd는 목표값이며 현재 실제 heading 관측이 아니다. 따라서 절대 경로 복귀 기능은 확인되지 않는다.
- 공식 예제는 command norm <=0.05에서 Balance 정책으로 전환한다. 현재 명령 sweep의 standstill은 Walk 정책을 계속 사용했다. 이전 standstill 결과는 공식 Balance 동작 검증으로 인용하면 안 된다.
- 공식 XML 기본 spawn z=0.793 m, 실험 protocol z=0.8 m이다. 초기 transient 기여는 추가 A/B가 필요하다.
- 공식 YAML의 ft92/ft109 경로와 실제 사용한 공개 Balance/Walk 파일명이 다르므로, 이번 소스 비교만으로 공식 checkpoint 실행과 완전히 동일하다고 주장할 수 없다.

## 확인된 평가 문제

1. worker가 이미 local-frame인 free-joint qvel[3:6]에 R.T를 다시 적용한다. body yaw-rate RMSE는 직접 qvel[5]로 평가해야 한다. 1초 warmup 이후 기존 mean/RMSE=-0.016087/0.252117, 재계산 mean/RMSE=-0.015830/0.222348 rad/s다. 실제 Euler heading 변화율은 body z 각속도와 별도 지표로 다뤄야 한다.
2. slip 지표는 접촉 중 발목 body 원점의 수평 이동을 측정한다. 발 회전만으로 원점이 움직일 수 있어 실제 접촉점의 지면 상대 미끄러짐으로 볼 수 없다. 지면 이외 접촉도 포함될 수 있다.
3. command tracking은 m/s와 rad/s 세 RMSE에 동일한 0.35 수치를 적용하고 world heading/path 오차를 검사하지 않는다. 따라서 이전 SUCCESS는 직진 성능 보장이 아니다.
4. 수치 불안정 종료도 execution.valid=true 및 standing=false로 반환한다. 시뮬레이터 수치 발산을 물리적 낙상과 구분해야 한다.

이전에 보고한 마찰/push tracking 경계는 해당 평가식과 임계값에서 관측된 표본 구간이다. 각속도 지표 수정 후 재평가가 필요하고, 보편적 로봇 성능 한계로 인용하지 않는다. 낙상 경계도 고정 초기조건과 외력 시점에서 얻은 표본 구간이며 단조성이나 일반성은 증명되지 않았다.

## 권고

먼저 평가 좌표계와 failure 분류를 수정하고 기존 궤적을 재평가한다. 이후 초기화 및 공식 Balance-to-Walk 전환의 A/B로 방향 bias 원인을 분리한다. heading/path 유지가 필요한 실험에는 상위 heading controller를 별도 버전의 정책으로 추가하고 원본 정책 결과와 비교한다. 현재 근거만으로 재학습이나 실제 하드웨어 변경 필요성을 판단할 수 없다.
