# Server/Client 연동 및 GPU 보행 통합 작업 기록

- 작업일: 2026-09-03 (UTC)
- 작업 경로: `/workspace/g1_failure/src/physical_ai_test_gen`
- 프로젝트: `scene2test`
- 런타임 산출물 루트: `/workspace/g1_failure/runtime`

## 1. 작업 목표

이번 작업의 목표는 다음과 같았다.

1. Simulation Server와 Dashboard를 실행하고 외부 접속 가능 상태를 확인한다.
2. Failure Client를 Server에 연결하여 실제 rollout 요청을 수행한다.
3. 실험 산출물의 기본 저장 위치를 작업용 런타임 경로로 통일한다.
4. JSON/YAML뿐이던 결과에 MP4, GIF, thumbnail을 추가한다.
5. 단순 G1 자세 고정 시뮬레이션에서 발생한 넘어짐을 해결한다.
6. GR00T-WBC의 학습된 ONNX 보행 정책을 NVIDIA GPU에서 실행한다.
7. 로봇이 실제로 서서 전진하는지 궤적, 이벤트 및 영상으로 검증한다.

## 2. Server와 Client 연동

### 2.1 기본 저장 경로 변경

생성 산출물이 소스 트리 또는 임시 폴더에 흩어지지 않도록 기본 경로를 다음과 같이 변경했다.

- Server: `/workspace/g1_failure/runtime/server`
- Client: `/workspace/g1_failure/runtime/client`

관련 변경 파일:

- `scene2test/src/simulation_server/config.py`
- `scene2test/src/failure_client/config.py`
- 관련 실행 문서 및 Client/Server 테스트

### 2.2 intervention 계약 불일치 수정

Client와 Server가 로봇 초기 자세 변경 operation을 서로 다른 형태로 해석하는 문제가 있었다.

- Client canonical kind: `robot_initial_state.set_spawn`
- method operation: `set_robot_spawn`
- canonical operation instance ID: `op_000`

Server가 canonical 형식과 기존 legacy 형식을 함께 처리하도록 조정했다. 이를 통해 Client가 생성한
rollout request가 Server의 authoritative validation을 통과하도록 했다.

## 3. 영상 및 시각 산출물 추가

Worker에 offscreen rollout recorder를 추가하여 다음 파일을 생성하도록 했다.

- `rollout.mp4`
- `rollout.gif`
- `thumbnail.png`

영상 기본 사양:

- 해상도: 640 × 480
- 프레임률: 20 FPS
- Linux 렌더링: MuJoCo EGL
- MP4 codec: H.264

Server artifact allowlist와 capability 정보에도 영상 산출물을 반영했다.

초기 legacy controller 영상 검증에서는 2초 동안 41프레임이 생성됐지만, base height가
약 1.325초에 임계값 아래로 떨어져 로봇이 넘어졌다. 이 결과는 렌더링 경로가 정상이라는
증거일 뿐 안정적인 standing 제어의 증거로 사용하지 않는다.

## 4. 넘어짐 원인 분석

### 4.1 단순 PD controller의 한계

기존 `mock_standing` / `hold_pose`는 MJCF keyframe 관절각을 유지하는 단순 PD 제어기였다.
이 제어기는 몸체 기울기, 각속도, 발 접촉 변화에 대응하는 동적 균형 정책이 아니므로 장시간
standing 또는 walking 기준선으로 사용할 수 없었다.

### 4.2 학습 정책이 실행 경로에 연결되지 않음

GR00T-WholeBodyControl 저장소에는 다음 정책이 존재했지만 기존 Simulation Server는 이를
로드하거나 추론하지 않았다.

- `GR00T-WholeBodyControl-Balance.onnx`
- `GR00T-WholeBodyControl-Walk.onnx`

두 모델 모두 516차원 입력과 15차원 action 출력을 사용한다. 516차원 입력은 86차원 상태의
6-step history로 구성된다.

### 4.3 projected-gravity 좌표계 부호 오류

첫 통합 실행에서는 quaternion으로부터 계산한 projected gravity의 x/y 부호가 정책 학습 시
사용된 convention과 반대였다. 정책이 기울어진 방향을 반대로 관측하면서 잘못된 자세 보정을
수행했고, 0.89초에 base-height threshold를 통과하며 넘어졌다.

실패 job:

- Job ID: `job_9cc8bfba125641418fd185e21fc1ee30`
- 최종 base height: 약 0.088 m
- 전진 거리: 약 -0.057 m
- lateral displacement: 약 -1.292 m
- 판정: `standing_at_end=false`, `walked_forward=false`

projected gravity x/y의 부호를 GR00T-WBC 정책 convention에 맞게 수정한 뒤 standalone 및
통합 rollout에서 안정성을 회복했다.

## 5. GR00T-WBC locomotion 구현

새 모듈 `scene2test/src/simulation_server/groot_locomotion.py`에 `G1OnnxController`를
추가했다.

주요 기능:

- native `g1_gear_wbc.xml` 모델 로드
- Balance/Walk ONNX 정책 선택
- 6 × 86 observation history 구성
- ONNX Runtime 추론
- 15개 정책 action을 목표 관절 상태로 변환
- 모델과 동일한 PD gain 및 control decimation 적용
- 실제 사용한 execution provider를 reproduction manifest에 기록

Server registry에는 다음 resource를 추가했다.

- Scene: `g1_locomotion_ground`
- Robot: `unitree_g1_locomotion`, profile `29dof`
- Controller: `groot_balance`, `groot_locomotion`
- Policy: `groot_balance_policy`, `groot_walk_policy`
- Task: `locomotion@1.0`

locomotion task는 다음 명령을 받는다.

- `linear_velocity_x`
- `linear_velocity_y`
- `yaw_rate`
- `minimum_forward_distance_m`

결과에는 다음 task fact를 기록한다.

- `standing_at_end`
- `final_base_height_m`
- `forward_distance_m`
- `lateral_distance_m`
- `walked_forward`

## 6. GPU 실행 환경

확인된 GPU:

- NVIDIA RTX PRO 4000 Blackwell
- GPU memory: 24,467 MiB

처음 설치한 최신 ONNX Runtime GPU 패키지는 CUDA 13의 `libcublasLt.so.13`을 요구했지만
실제 런타임 라이브러리는 CUDA 12 계열이어서 provider 초기화에 실패했다. 이후
`onnxruntime-gpu==1.22.0`으로 고정하여 CUDA 12 환경과 호환시켰다.

검증 결과:

- Available provider: `CUDAExecutionProvider`, `CPUExecutionProvider`
- Session provider: `CUDAExecutionProvider`, `CPUExecutionProvider`
- 실제 worker GPU 점유: 약 489 MiB
- reproduction manifest provider: `CUDAExecutionProvider`

`SIM_SERVER_ONNX_PROVIDER=cuda`가 기본 동작이다. CUDA provider 초기화에 실패하면 조용히
CPU로 폴백하지 않고 오류를 발생시키도록 하여 실험 provenance가 모호해지지 않게 했다.

## 7. Worker timeout 문제와 수정

첫 GPU 통합 실행은 정책 오류가 아니라 Server timeout 때문에 실패했다.

- 실패 Job ID: `job_81ceb4d16c30446eb1049af5f4978691`
- termination reason: `WORKER_TIMEOUT`
- 기존 제한: simulation duration + 30초

CUDA context, ONNX session 및 renderer 초기화가 30초의 여유시간을 약간 넘었다. 이에
worker startup grace를 기본 120초로 변경하고 다음 환경 변수로 설정 가능하게 했다.

```text
SIM_SERVER_WORKER_STARTUP_GRACE_S=120
```

이 제한은 실제 simulation duration과 별도로 더해진다.

## 8. 최종 GPU 보행 검증

최종 실험:

- Experiment ID: `exp_g1_locomotion_gpu_final_20260903`
- Job ID: `job_68f68d4a74bc4ebcaf539888799e5aea`
- 정책 명령: forward 0.3 m/s, lateral 0.0 m/s, yaw 0.0 rad/s
- simulation duration: 5.0초
- physics steps: 1,000
- trajectory samples: 1,001
- contact samples: 4,298
- rendered frames: 101

결과:

| 항목 | 결과 |
|---|---:|
| Execution | `SUCCEEDED` |
| ONNX provider | `CUDAExecutionProvider` |
| 최저 base height | 0.736635 m |
| 최종 base height | 0.743857 m |
| 전진 거리 | 1.173314 m |
| lateral displacement | -0.313288 m |
| `standing_at_end` | `true` |
| `walked_forward` | `true` |
| base-height failure event | 없음 |
| Client confirmed failures | 0 |

최종 산출물 폴더:

```text
/workspace/g1_failure/runtime/server/outputs/jobs/job_68f68d4a74bc4ebcaf539888799e5aea
```

생성 파일:

- `execution_result.json`
- `state_trajectory.jsonl`
- `action_trajectory.jsonl`
- `contacts.jsonl`
- `reproduction.json`
- `rollout.mp4`
- `rollout.gif`
- `thumbnail.png`
- `worker.log`

MP4 검증값:

- codec: H.264
- resolution: 640 × 480
- frame rate: 20 FPS
- duration: 5.05초
- frames: 101

## 9. 검증 및 품질 확인

- 전체 테스트 결과: 58 passed, 1 warning
- 변경 파일 대상 Ruff 검사: 통과
- `git diff --check`: 통과
- Server health: `status=ok`, backend=`groot_mujoco`

전체 저장소에 대한 Ruff 검사는 기존 Scene2Test/LAM 코드에 있던 미정리 lint 문제 때문에
통과하지 않는다. 이번 변경 파일을 대상으로 한 검사는 통과했으며 기존 lint 문제를 이번
작업의 회귀로 해석하지 않는다.

## 10. 주요 변경 파일

- `scene2test/src/simulation_server/groot_locomotion.py` (신규)
- `scene2test/src/simulation_server/worker.py`
- `scene2test/src/simulation_server/bootstrap.py`
- `scene2test/src/simulation_server/main.py`
- `scene2test/src/simulation_server/jobs.py`
- `scene2test/src/simulation_server/config.py`
- `scene2test/src/failure_client/config.py`
- `scene2test/config/failure_client_locomotion_smoke.yaml` (신규)
- `scene2test/pyproject.toml`
- `scene2test/uv.lock`
- `scene2test/docs/SIMULATION_SERVER.md`
- `scene2test/docs/CLIENT_SERVER_RUNBOOK.md`
- Client/Server 관련 테스트 파일

## 11. 현재 한계 및 후속 연구 주제

이번 검증으로 확인된 것은 평지에서 지정된 속도 명령을 받은 학습 보행 정책이 5초 동안
넘어지지 않고 전진한다는 것이다. 다음 항목은 아직 별도 검증이 필요하다.

- 더 긴 시간의 보행 안정성 및 반복 실행 통계
- lateral displacement 감소 및 trajectory tracking 오차 분석
- 속도, 방향 및 yaw command sweep
- 지면 마찰, 경사, 외력, 장애물 intervention
- 넘어짐 이외의 slip, foot clearance, torque/energy 안전 margin
- GPU warm-up 이후 latency 및 throughput benchmark
- 여러 worker의 GPU memory contention과 병렬 실행 제한
- 실제 센서 관측 및 sim-to-real 조건

따라서 현재 결과는 “5초 평지 GPU 보행 E2E 성공”으로 기술해야 하며, 모든 환경에서의
보행 안정성이나 실제 로봇 적용 가능성을 입증한 것으로 확대 해석해서는 안 된다.
