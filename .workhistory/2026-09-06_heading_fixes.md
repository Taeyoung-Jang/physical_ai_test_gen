# 보행 평가 수정과 직선 경로 유지 검증

2026-09-06 UTC. 사용자 승인에 따라 9월 6일 검토에서 확인한 문제를 수정했다.

## 변경

- Metrics version 2.0: MuJoCo free-joint angular velocity를 이미 body frame인 값으로 사용한다. 기존 R.T 중복 회전을 제거했다.
- 발 미끄러짐은 ankle/plane의 실제 접촉점에서 두 body의 Jacobian 기반 속도 차이를 계산하고 접촉면 접선 성분만 사용한다. 발목 원점의 이동량을 사용하는 기존 지표와 구별된다. 접촉점 표본 가중 RMS이며 발별 균등 가중값은 아니다.
- simulation time 역행/비유한 상태는 execution.valid=false, NUMERICAL_INSTABILITY로 반환한다. standing은 미정(None), 실제 height 낙상 관측은 fall_observed로 보존한다. Client evaluator는 INDETERMINATE로 처리한다.
- 선속도와 각속도 RMSE 허용값을 각각 m/s와 rad/s 옵션으로 분리하고 양의 유한값 검증을 추가했다. 기존 단일 tolerance는 호환 기본값으로 남겼다.
- straight_path_success: 초기 heading 기준 최대 횡오차 <=0.2 m, 최대 wrapped heading 오차 <=0.2 rad, 낙상 없음, 정상 완료. 회전/횡이동 명령에는 적용하지 않는다.
- path_hold=true는 전진 전용 명령에서 명시적으로 선택한다. straight-path-v1 supervisor가 yaw command = clip(-1.5*heading_error -0.8*cross_track, -0.5,0.5)를 생성한다. ONNX 가중치는 그대로다. 기본 원본 정책 모드는 보정하지 않는다.
- supervisor와 metrics 버전, nominal command를 reproduction에 기록하고 매 step command를 action trajectory에 기록한다. 보정 모드 RMSE는 해당 step의 보정된 명령 대비 값이다. 절대 경로 성능은 별도 straight_path_success로 평가한다.
- 영상 카메라가 robot base XY를 추적하도록 변경했다.

## 30초 CUDA A/B

평지, spawn z=0.8 m, forward command 0.3 m/s, physics dt=0.005, 각 6000 step.

| 지표 | 원본 명령 | 경로 유지 |
|---|---:|---:|
| 전진 거리 (m) | 6.976037 | 7.550314 |
| 최종 횡편차 (m) | -2.870735 | -0.050632 |
| 최대 횡편차 (m) | 2.870735 | 0.122616 |
| 최대 heading 오차 (rad) | 0.605693 | 0.110737 |
| 최저 base 높이 (m) | 0.736635 | 0.736852 |
| 낙상 | 없음 | 없음 |
| 직선 경로 기준 | 실패 | 성공 |

직접 worker 비교 산출물: `/workspace/g1_failure/runtime/reviews/20260906/raw/`, `path_hold/`.
원본 모드는 기존 30초 궤적과 동일한 최종 위치를 재현했다. 따라서 새 지표 계산이 해당 실행의 운동을 바꾸지 않았다.

Client 영상 포함 검증: `exp_g1_path_hold_30s_20260906`, job `job_3591ebb1b5ba4b74b7182a1e002c189c`. evaluation=1, failure=0. 추적 카메라 최종 실행은 `exp_g1_path_hold_30s_follow_20260906`이다.

## 수치 발산 및 과거 결과

마찰 0 CUDA 재검증: `/workspace/g1_failure/runtime/reviews/20260906/zero_friction/execution_result.json`. NUMERICAL_INSTABILITY, valid=false, standing=None, fall_observed=false. 원시 수치 발산을 실제 낙상으로 해석하지 않는다.

`tools/review_saved_heading.py`로 기존 30초 기록의 yaw RMSE를 0.222348 rad/s로 재평가하고 직선 경로 실패를 확인했다. 결과는 `runtime/reviews/20260906/previous_30s_reevaluation.json`에 분리 저장했다. 과거 Client DB와 원시 산출물은 덮어쓰지 않았다. 모든 과거 sweep의 재판정까지 수행한 것은 아니며 이전 tracking 경계는 v1 평가식 결과로 남는다.

## 검증과 한계

- Server 및 Client evaluator 관련 테스트 16개 통과, Ruff 통과.
- 회귀 테스트: 기울어진 free-joint 각속도를 mj_objectVelocity와 대조, 움직이는 발목의 구름 접촉에서 slip=0, 상대 미끄러짐 0.2 m/s, 경로 frame/방향 보정 부호.
- 새 supervisor는 단일 평지/속도에서 확인했다. 외력·경사·다른 속도에서의 강건성을 입증하지 않는다.
- 공식 예제와의 초기높이/Balance-to-Walk 전환 A/B는 아직 수행하지 않았다. drift의 근본 원인을 모델 자체로 단정하지 않는다.
- 원본 Walk 정책의 무명령 동작은 자동 Balance 전환으로 바꾸지 않았다. 기존 zero-command sweep은 Walk 결과로 해석한다.

최종 추적 영상 job: `job_f3ece72b5ab24be0bc549a6c4fe74829`. 산출물: `/workspace/g1_failure/runtime/server/outputs/jobs/job_f3ece72b5ab24be0bc549a6c4fe74829`. CUDAExecutionProvider 및 straight_path_success=true 확인.
