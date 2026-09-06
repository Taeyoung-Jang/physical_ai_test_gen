# GPU 보행 연구 기준선 및 Failure Sweep

- 작업일: 2026-09-03 (UTC)
- 선행 기록: `2026-09-03_server_client_gpu_locomotion.md`
- runtime: `/workspace/g1_failure/runtime`

## 목표와 수행 범위

단일 성공 사례를 연구 기준선으로 확장하기 위해 20회 GPU 반복, 보행 평가 지표 확장,
9개 명령 sweep, 마찰·측면 외력 intervention, failure boundary sweep, 자동 보고서 생성을 수행했다.

## 20회 GPU 반복 기준선

- Experiment: `exp_g1_locomotion_baseline_20_20260903`
- 조건: 평지, 5초, 전진 명령 0.3 m/s
- 유효/성공/CUDA/영상: 모두 20/20
- 낙상: 0
- 전진 거리: 평균 1.173314 m, 표준편차 0
- 횡방향 이동: 평균 -0.313288 m, 표준편차 0
- 최저/최종 base 높이: 0.736635 / 0.743857 m
- wall time: 평균 18.807559초, 표준편차 0.861146초, 범위 17.949473~22.202469초

운동학 분산이 0인 것은 seed가 초기 물리 상태나 noise에 반영되지 않고 MuJoCo와 ONNX가
같은 조건에서 결정론적으로 실행되기 때문이다. 확률적 강건성의 증거로 해석하지 않는다.
보고서: `/workspace/g1_failure/runtime/reports/exp_g1_locomotion_baseline_20_20260903/`

## 확장한 평가 지표

각 rollout에 최저 base 높이, 최대 roll/pitch, 최종 roll/pitch/yaw, heading 변화,
body-frame 평균 x/y/yaw 속도, 속도 RMSE, command tracking 판정, torque RMS/최대값,
평균 absolute mechanical power, 접촉 중 foot-slip RMS/최대값을 기록한다.

명목 0.3 m/s 대표값은 forward RMSE 0.044947 m/s, lateral RMSE 0.122414 m/s,
yaw RMSE 0.250927 rad/s, 최대 roll/pitch 0.105102/0.123683 rad, torque RMS
8.210468 Nm, power 70.365559 W, contact-slip RMS 0.067378 m/s였다.

## 9개 명령 Sweep

- Prefix: `exp_g1_command_sweep_20260903`
- 9조건 × 3회 = 27 CUDA rollout
- 유효 및 standing+tracking 성공: 27/27
- 조건: 정지, 전진 0.1/0.3/0.6, 후진 -0.2, 횡이동 ±0.2 m/s, 회전 ±0.5 rad/s
- 0.6 m/s 전진: 2.529 m, forward RMSE 0.061 m/s
- -0.2 m/s 후진: -0.870 m, RMSE 0.028 m/s
- 좌/우 횡이동: +0.634 / -0.743 m
- 좌/우 회전 heading: +2.333 / -2.586 rad

명목 전진의 world lateral displacement는 -0.313 m이나 body-frame 평균 lateral velocity는
거의 0이었다. heading drift가 경로 편차에 기여한다.
보고서: `/workspace/g1_failure/runtime/reports/exp_g1_command_sweep_20260903/`

## Dynamics intervention

`dynamics.set_friction`은 coefficient [0,2]를 MuJoCo sliding friction에 적용한다.
`dynamics.apply_external_force`는 body, force vector(각 성분 ±1000 N), 시작 시간, duration을
검증하고 지정 구간에 `xfrc_applied`로 적용한다. 적용값은 reproduction manifest에 기록한다.

## 마찰 Sweep

- Experiment: `exp_g1_friction_sweep_20260903`
- 계수: 1.0, 0.8, 0.6, 0.4, 0.2, 0.1, 0.05, 0.0
- 1.0~0.4: standing/forward/tracking 성공
- 0.2와 0.1: standing/forward 성공, tracking 실패
- 0.05: 낙상, 최저 높이 0.091 m, slip RMS 3.606 m/s
- coarse tracking 경계: 0.2~0.4
- coarse 낙상 경계: 0.05~0.1

보고서: `/workspace/g1_failure/runtime/reports/exp_g1_friction_sweep_20260903/`

## 측면 Push Sweep

- Experiment: `exp_g1_lateral_push_sweep_20260903`
- pelvis +Y, simulation 2.0초부터 0.2초간 0~600 N
- 0~200 N: standing/tracking 성공
- 300/400 N: standing 유지, tracking 실패
- 600 N: 낙상, 최저 높이 0.165 m, 최대 roll 3.129 rad
- coarse tracking 경계: 200~300 N
- coarse 낙상 경계: 400~600 N

보고서: `/workspace/g1_failure/runtime/reports/exp_g1_lateral_push_sweep_20260903/`

## 수치 불안정 무한-loop 버그

마찰 0.0에서 MuJoCo가 QACC/CTRL 발산 후 simulation time을 0으로 되돌렸다. 기존
`data.time < duration` loop가 끝나지 않아 125초 후 timeout됐고 state 152 MiB, action
41 MiB, contacts 141 MiB 등 총 약 333 MiB를 생성했다.

수정 후에는 maximum step count, finite state, time progress를 검사하고 수치 불안정 시
`NUMERICAL_INSTABILITY` 이벤트로 즉시 종료한다. 재검증 experiment는
`exp_g1_zero_friction_bounded_20260903`, job은
`job_7cb07b977013435f87ab3b31c9739ee3`이다. 24 step/0.115초에서 종료되어 Client가 failure로
판정했고 artifact는 약 0.48 MiB였다. 최초 333 MiB 증거는 삭제하지 않았다.

## 추가 파일

설정: `failure_client_locomotion_baseline_20.yaml`, `locomotion_command_sweep.yaml`,
`failure_client_friction_sweep.yaml`, `failure_client_push_sweep.yaml`.
도구: `report_locomotion_baseline.py`, `run_locomotion_command_sweep.py`,
`report_locomotion_sweep.py`, `report_dynamics_sweep.py`.

## 다음 연구 단계

1. 마찰 0.2~0.4 및 0.05~0.1 경계 refinement
2. push 200~300 N 및 400~600 N 경계 refinement
3. seed가 실제 변동을 만들도록 마찰·질량·sensor noise 분포 정의
4. 경사면 및 장애물 intervention
5. 장시간/병렬 GPU soak test
6. 지표별 안전 임계값의 versioned failure definition 고정

## 검증 결과

- 변경 범위 테스트: 13 passed, 1 deprecation warning
- 변경 파일 Ruff: 통과
- `git diff --check`: 통과
- Server health: `ok`, backend `groot_mujoco`
- broad test: 72 passed, 1 failed, 1 error

Broad test의 미통과 2건은 이번 변경 범위 밖의 기존 환경/phase-script 문제다. 하나는 optional
`trimesh` dependency 미설치(`test_p18_sources.py`)이고, 다른 하나는 executable phase script의
`test_mutation_filter_speed(sg)`가 pytest fixture로 존재하지 않는 `sg`를 요구하는 문제다.
새 dynamics 및 locomotion 변경 범위 테스트는 모두 통과했다.

## Boundary refinement

추가 protocol은 `/workspace/g1_failure/runtime/protocols/dynamics_refinement_20260903/`에
보존했다.

- 마찰: 0.30 성공, 0.25/0.15 tracking 실패, 0.075 낙상
- 최종 coarse tracking 경계: coefficient 0.25~0.30
- 최종 coarse 낙상 경계: coefficient 0.075~0.10
- push: 225/250/275/450/500/550 N은 모두 standing 유지, tracking 실패
- 최종 coarse tracking 경계: 200~225 N
- 최종 coarse 낙상 경계: 550~600 N

보고서:

- `/workspace/g1_failure/runtime/reports/exp_g1_friction_refinement_20260903/`
- `/workspace/g1_failure/runtime/reports/exp_g1_push_refinement_20260903/`

## 30초 GPU soak

- Experiment: `exp_g1_locomotion_30s_soak_20260903`
- Job: `job_4431768dcfdd4056adae0a8cc284dada`
- CUDA, 6000 physics steps, 영상 비활성화
- standing/tracking 성공, 낙상 없음
- 전진 6.976 m, 횡편차 -2.871 m, heading drift -0.606 rad
- 최저/최종 base 높이 0.736635/0.743965 m
- forward/lateral/yaw RMSE 0.047503/0.122552/0.252117

장시간에도 자세와 body-frame 속도 추종은 유지했지만 world-frame 경로 편차가 크게 누적됐다.
후속 연구에서는 yaw bias와 path tracking을 별도 failure criterion으로 다뤄야 한다.
