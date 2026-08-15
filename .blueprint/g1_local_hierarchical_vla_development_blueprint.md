# Apple Silicon 로컬 Unitree G1 Vision-Language Navigation 개발 청사진

- 문서 목적: Coding Agent가 별도 질의 없이 구현을 시작할 수 있는 기술 명세
- 대상 플랫폼: Apple Silicon macOS
- 기준일: 2026-08-15
- 프로젝트 코드명: `g1-local-nav`
- 우선 로봇: Unitree G1 29-DoF
- 시뮬레이터: MuJoCo
- 저수준 제어기: LeRobot `GrootLocomotionController`
- 상위 시각-언어 모델: `mlx-community/SmolVLM2-500M-Video-Instruct-mlx`
- 클라우드 및 CUDA: 사용하지 않음

---

## 1. 프로젝트 목표

Apple Silicon MacBook 한 대에서 다음 폐루프 시스템을 구현한다.

```text
MuJoCo Unitree G1 head camera
            +
자연어 지시: "Move toward the red box and stop near it."
            ↓
로컬 MLX Vision-Language Model
            ↓
고수준 이산 행동
FORWARD | TURN_LEFT | TURN_RIGHT | STOP
            ↓
LeRobot action adapter
remote.lx / remote.ly / remote.rx / remote.ry
            ↓
pretrained GR00T Balance/Walk ONNX controller, 50 Hz
            ↓
Unitree G1 lower-body joint targets
            ↓
MuJoCo physics
            ↓
새 카메라 관찰
```

첫 번째 완성 과업은 다음 하나로 제한한다.

> **빨간 상자를 찾아 그 방향으로 걸어가고, 가까워지면 멈춘다.**

이 프로젝트에서 모델을 새로 학습하거나 fine-tuning하지 않는다.

---

## 2. 정확한 기술적 정의

이 시스템은 **하나의 end-to-end pretrained humanoid VLA**가 아니다.

정확한 명칭은 다음과 같다.

> **Hierarchical Vision-Language-to-Locomotion System for Language-Conditioned Humanoid Navigation**

역할 분리는 다음과 같다.

| 계층 | 컴포넌트 | 역할 |
|---|---|---|
| 고수준 정책 | SmolVLM2 | 이미지와 언어 지시를 보고 이산 이동 행동 선택 |
| Action adapter | 프로젝트 자체 코드 | 이산 행동을 LeRobot의 remote 축 값으로 변환 |
| 저수준 정책 | `GrootLocomotionController` | 속도 명령과 로봇 상태를 관절 목표값으로 변환하고 균형 유지 |
| 물리 환경 | MuJoCo | G1 동역학, 접촉, 카메라 렌더링 |

문서, 코드 주석, README에서 SmolVLM2 자체를 VLA라고 부르지 않는다. 전체 시스템을 `hierarchical VLA-like system`, `VLM-to-locomotion system` 또는 위의 정확한 명칭으로 표현한다.

---

## 3. 현재 공식 구현에서 재사용할 사실

Coding Agent는 아래 upstream 인터페이스를 최대한 그대로 재사용하고, LeRobot 내부를 대규모로 fork하지 않는다.

1. LeRobot은 Unitree G1 29/23-DoF와 MuJoCo simulation 경로를 제공한다.
2. 공식 G1 simulation 명령은 `GrootLocomotionController` 또는 `HolosomaLocomotionController`를 선택할 수 있다.
3. `GrootLocomotionController`는 Hugging Face Hub에서 다음 ONNX 파일을 내려받는다.
   - `GR00T-WholeBodyControl-Balance.onnx`
   - `GR00T-WholeBodyControl-Walk.onnx`
4. controller 주기는 `0.02 s`, 즉 50 Hz이다.
5. controller 입력의 핵심은 다음 remote 축이다.
   - `remote.ly`: 전진/후진
   - `remote.lx`: 좌우 이동
   - `remote.rx`: 회전
   - `remote.ry`: 현재 controller에서는 locomotion 핵심 입력으로 사용하지 않음
6. LeRobot `UnitreeG1.send_action()`은 remote 입력을 controller thread에 전달한다.
7. LeRobot `UnitreeG1.get_observation()`은 관절/IMU 상태와 설정된 ZMQ 카메라 이미지를 반환한다.
8. G1 MuJoCo EnvHub는 `head_camera`를 기본 640×480, 약 30 Hz로 ZMQ publish할 수 있다.
9. MuJoCo의 공식 macOS 배포판은 universal binary이며 Python wheel은 `pip install mujoco`로 설치할 수 있다.
10. MLX-VLM은 Apple Silicon에서 로컬 VLM inference를 지원한다.

주의: 공식 LeRobot G1 문서는 Python 3.12, `unitree_sdk2py==1.0.1`, `cyclonedds==0.10.2` 조합을 테스트 대상으로 명시하지만, **Apple Silicon에서 전체 G1 DDS 경로가 완전히 검증되었다고 명시하지는 않는다.** 따라서 Darwin 호환성 검증을 첫 번째 milestone으로 둔다.

---

## 4. 범위

### 4.1 반드시 구현할 범위

- Apple Silicon에서 MuJoCo G1 simulation 실행
- pretrained GR00T Balance/Walk ONNX controller 실행
- 게임패드 또는 programmatic command로 G1 전진·회전·정지 확인
- head camera RGB frame 획득
- MLX-VLM 별도 로컬 프로세스 실행
- 제한된 고수준 행동 4개 출력
- VLM action을 LeRobot remote action으로 변환
- closed-loop `sense → decide → act → stop` 실행
- episode log, frame, raw model output, action, latency 저장
- timeout/failure 시 즉시 STOP
- red-box navigation용 최소 MuJoCo scene
- 간단한 success metric과 결과 요약

### 4.2 구현하지 않을 범위

- 로봇 팔 manipulation
- grasping 또는 loco-manipulation
- VLM/VLA fine-tuning
- RL locomotion policy 학습
- 실제 Unitree G1 하드웨어 배포
- CUDA, Docker CUDA image, AWS, RunPod, Colab
- 복잡한 SLAM, 3D reconstruction, global path planning
- 여러 방 또는 장거리 navigation
- 음성 입력
- continuous end-to-end joint action을 생성하는 VLA

---

## 5. 최종 시스템 아키텍처

### 5.1 프로세스 구성

의존성 충돌과 장애 격리를 위해 최소 2개 프로세스로 나눈다.

```text
Process A: simulator_and_control
Conda env: g1-sim

- LeRobot UnitreeG1
- MuJoCo EnvHub
- GrootLocomotionController / ONNX Runtime
- head camera client
- action adapter
- safety watchdog
- episode manager
- metrics/logger

                localhost HTTP
                       ↓↑

Process B: vlm_server
Conda env: g1-vlm

- FastAPI
- MLX-VLM
- SmolVLM2-500M
- prompt builder
- strict action parser
```

### 5.2 주기

| 루프 | 목표 주기 | 비고 |
|---|---:|---|
| MuJoCo physics | upstream 기본 250 Hz | EnvHub 설정을 먼저 유지 |
| GR00T locomotion controller | 50 Hz | LeRobot background thread가 유지 |
| 카메라 | 약 30 Hz | 매 추론마다 최신 frame 1장만 사용 |
| VLM inference | 초기 0.5–1.0 Hz | Mac 사양에 따라 측정 후 결정 |
| high-level action chunk | 0.25–0.40 s | 각 chunk 뒤 STOP 적용 |
| watchdog | 10 Hz 이상 | stale command 및 timeout 감시 |

첫 버전은 연속 명령 방식이 아니라 다음의 안전한 chunked control을 사용한다.

```text
STOP
  ↓
최신 이미지 획득
  ↓
VLM inference
  ↓
행동을 0.25~0.40초 적용
  ↓
STOP
  ↓
다음 관찰
```

VLM 추론 중 이전 이동 명령을 계속 유지하지 않는다. 이렇게 해야 느린 추론 때문에 로봇이 계속 걸어가는 overshoot를 줄일 수 있다.

---

## 6. 권장 저장소 구조

```text
g1-local-nav/
├── README.md
├── AGENTS.md
├── LICENSE
├── .gitignore
├── Makefile
│
├── configs/
│   ├── app.yaml
│   ├── action_map.yaml
│   ├── scene.yaml
│   └── logging.yaml
│
├── prompts/
│   └── red_box_navigation.txt
│
├── envs/
│   ├── g1-sim.environment.yml
│   └── g1-vlm.environment.yml
│
├── scripts/
│   ├── bootstrap_macos.sh
│   ├── verify_platform.py
│   ├── run_upstream_manual_smoke.sh
│   ├── run_scripted_motion.py
│   ├── run_camera_smoke.py
│   ├── run_vlm_server.sh
│   ├── run_closed_loop.sh
│   └── collect_diagnostics.sh
│
├── services/
│   └── vlm_server/
│       ├── app.py
│       ├── model.py
│       ├── prompt.py
│       ├── parser.py
│       └── schemas.py
│
├── src/
│   └── g1_local_nav/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── robot_runtime.py
│       ├── vlm_client.py
│       ├── action.py
│       ├── action_mapper.py
│       ├── control_loop.py
│       ├── safety.py
│       ├── episode.py
│       ├── metrics.py
│       ├── recorder.py
│       └── scene_adapter.py
│
├── assets/
│   ├── scenes/
│   │   └── red_box_nav.xml
│   └── third_party_notices/
│
├── tests/
│   ├── unit/
│   │   ├── test_action_parser.py
│   │   ├── test_action_mapper.py
│   │   ├── test_watchdog.py
│   │   └── test_config.py
│   ├── integration/
│   │   ├── test_vlm_api.py
│   │   ├── test_scripted_sim.py
│   │   └── test_recorded_frame_policy.py
│   └── fixtures/
│       └── frames/
│
├── runs/
│   └── .gitkeep
│
└── THIRD_PARTY.lock.md
```

`runs/`, Hugging Face cache, downloaded ONNX weights, VLM weights는 Git에 commit하지 않는다.

---

## 7. 환경 전략

### 7.1 공통 요구사항

- Native ARM64 terminal을 사용한다. Rosetta x86 Python을 사용하지 않는다.
- `uname -m` 결과는 `arm64`여야 한다.
- Python 3.12를 기본으로 한다.
- Miniforge/Conda 사용을 권장한다.
- Git LFS를 설치한다.
- 최초 성공 후 모든 upstream commit SHA와 model revision을 고정한다.

### 7.2 simulation 환경

초기 설치 기준:

```bash
conda create -n g1-sim python=3.12 -y
conda activate g1-sim

conda install -c conda-forge ffmpeg -y
conda install -c conda-forge "pinocchio>=3.0.0,<4.0.0" -y

brew install git-lfs
git lfs install

git clone https://github.com/unitreerobotics/unitree_sdk2_python.git third_party/unitree_sdk2_python
pip install -e third_party/unitree_sdk2_python

git clone https://github.com/huggingface/lerobot.git third_party/lerobot
pip install -e 'third_party/lerobot[unitree_g1]'

pip install \
  mujoco \
  loguru \
  msgpack \
  msgpack-numpy \
  opencv-python \
  pyzmq \
  pyyaml \
  httpx \
  pydantic \
  typer \
  rich
```

주의사항:

- zsh에서 extras 구문은 반드시 작은따옴표로 감싼다.
- `pinocchio`는 공식 문서대로 conda-forge에서 설치한다.
- `unitree_sdk2py` 및 `cyclonedds` 버전은 upstream smoke test가 성공한 조합으로 고정한다.
- `pip freeze`만으로 Conda 패키지를 완전히 재현할 수 없으므로 `environment.yml`도 생성한다.

### 7.3 VLM 환경

```bash
conda create -n g1-vlm python=3.12 -y
conda activate g1-vlm

pip install -U \
  mlx-vlm \
  fastapi \
  'uvicorn[standard]' \
  pillow \
  python-multipart \
  pydantic \
  orjson
```

기본 모델:

```text
mlx-community/SmolVLM2-500M-Video-Instruct-mlx
```

모델 ID는 코드에 하드코딩하지 않고 `configs/app.yaml`에서 변경 가능하게 한다.

---

## 8. Upstream 수동 smoke test

새 기능을 작성하기 전에 공식 경로가 Mac에서 동작하는지 검증한다.

```bash
conda activate g1-sim
cd third_party/lerobot

lerobot-teleoperate \
  --robot.type=unitree_g1 \
  --robot.is_simulation=true \
  --teleop.type=unitree_g1 \
  --teleop.id=wbc_unitree \
  --robot.cameras='{"global_view": {"type": "zmq", "server_address": "localhost", "port": 5555, "camera_name": "head_camera", "width": 640, "height": 480, "fps": 30, "warmup_s": 5}}' \
  --display_data=true \
  --robot.controller=GrootLocomotionController
```

검증 항목:

1. MuJoCo window가 열린다.
2. G1 model과 바닥이 보인다.
3. Balance/Walk ONNX 파일이 다운로드되고 ONNX Runtime session이 생성된다.
4. lowstate 수신 timeout이 발생하지 않는다.
5. controller actual rate 로그가 목표 50 Hz에 근접한다.
6. head camera ZMQ client가 frame을 받는다.
7. 게임패드가 있다면 전진·회전·정지가 된다.
8. 종료 시 child process와 viewer가 남지 않는다.

이 단계가 실패하면 application 코드를 작성하기 전에 `runs/diagnostics/`에 다음을 저장한다.

```text
macOS version
machine architecture
Python executable and version
Conda package list
pip freeze
LeRobot commit SHA
Unitree SDK commit SHA
MuJoCo version
onnxruntime version
cyclonedds version
full stack trace
```

---

## 9. Programmatic robot runtime

게임패드를 VLM action으로 교체하기 위해 CLI를 subprocess로 조작하지 않는다. LeRobot Python API를 직접 사용한다.

`robot_runtime.py`의 책임:

1. `UnitreeG1Config` 생성
2. simulation mode 활성화
3. `GrootLocomotionController` 선택
4. ZMQ head camera config 구성
5. `UnitreeG1.connect()` 호출
6. `get_observation()`과 `send_action()`을 감싼 안정적인 API 제공
7. 항상 STOP을 보낸 뒤 disconnect

권장 public interface:

```python
from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class RobotFrame:
    rgb: np.ndarray
    timestamp_ns: int
    imu_roll: float
    imu_pitch: float
    imu_yaw: float


class G1Runtime:
    def connect(self) -> None: ...
    def latest_frame(self) -> RobotFrame: ...
    def send_remote(self, command: Mapping[str, float]) -> None: ...
    def stop(self) -> None: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...
```

핵심 LeRobot action 형태:

```python
{
    "remote.lx": 0.0,
    "remote.ly": 0.0,
    "remote.rx": 0.0,
    "remote.ry": 0.0,
}
```

`send_remote()`은 내부적으로 `robot.send_action(action)`을 호출한다. controller background thread가 50 Hz로 lower-body joint command를 계속 생성한다.

---

## 10. 고수준 행동 명세

### 10.1 enum

```python
from enum import StrEnum


class NavAction(StrEnum):
    FORWARD = "FORWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    STOP = "STOP"
```

첫 버전에 `BACKWARD`, `STRAFE`, `LOOK_AROUND`를 추가하지 않는다.

### 10.2 action map

`configs/action_map.yaml` 예시:

```yaml
commands:
  FORWARD:
    remote.lx: 0.0
    remote.ly: 0.30
    remote.rx: 0.0
    remote.ry: 0.0

  TURN_LEFT:
    remote.lx: 0.0
    remote.ly: 0.0
    remote.rx: -0.25
    remote.ry: 0.0

  TURN_RIGHT:
    remote.lx: 0.0
    remote.ly: 0.0
    remote.rx: 0.25
    remote.ry: 0.0

  STOP:
    remote.lx: 0.0
    remote.ly: 0.0
    remote.rx: 0.0
    remote.ry: 0.0
```

주의: LeRobot controller 내부에서는 회전 명령에 `cmd[2] = -remote.rx`가 사용된다. 위 좌우 부호는 실제 viewer에서 반드시 calibration test를 수행하고 확정한다. 부호가 반대라면 YAML만 수정하며 코드 로직을 수정하지 않는다.

### 10.3 command clamp

모든 remote 값은 설정된 한계 내로 clamp한다.

```yaml
limits:
  remote.lx: [-0.35, 0.35]
  remote.ly: [-0.40, 0.40]
  remote.rx: [-0.35, 0.35]
  remote.ry: [-0.35, 0.35]
```

초기 값은 보수적으로 설정하고, 안정성 검증 후에만 확대한다.

---

## 11. VLM server 명세

### 11.1 API

```http
GET /health
```

응답:

```json
{
  "status": "ok",
  "model_loaded": true,
  "model_id": "mlx-community/SmolVLM2-500M-Video-Instruct-mlx"
}
```

```http
POST /v1/navigation-action
Content-Type: multipart/form-data
```

필드:

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `image` | JPEG/PNG file | O | 최신 head-camera RGB frame |
| `instruction` | string | O | 자연어 navigation goal |
| `previous_action` | enum string | X | action hysteresis용 |
| `episode_id` | string | O | 로깅 식별자 |
| `step_index` | integer | O | 로깅 식별자 |

응답:

```json
{
  "action": "TURN_LEFT",
  "raw_text": "TURN_LEFT",
  "latency_ms": 842.4,
  "model_id": "mlx-community/SmolVLM2-500M-Video-Instruct-mlx",
  "parse_ok": true
}
```

### 11.2 strict parser

모델의 raw output에서 다음 네 토큰만 허용한다.

```text
FORWARD
TURN_LEFT
TURN_RIGHT
STOP
```

파싱 규칙:

1. 공백, 따옴표, Markdown code fence 제거
2. 대문자화
3. 정확한 enum match
4. 문장에 enum이 하나만 포함되면 그 enum 사용
5. 0개 또는 2개 이상 포함되면 parse failure
6. parse failure의 최종 행동은 무조건 `STOP`

모델이 JSON을 생성하도록 강제하지 않는다. 500M 모델에서는 JSON 문법 오류가 추가 실패 원인이 될 수 있으므로 **한 개의 action token만 출력**하게 한다.

### 11.3 prompt

`prompts/red_box_navigation.txt`:

```text
You are the high-level navigation policy for a simulated Unitree G1 humanoid.

Goal:
{instruction}

Choose exactly one action from this list:
FORWARD
TURN_LEFT
TURN_RIGHT
STOP

Decision rules:
- If the red box is clearly left of the image center, choose TURN_LEFT.
- If the red box is clearly right of the image center, choose TURN_RIGHT.
- If the red box is near the image center and still appears far away, choose FORWARD.
- If the red box is very close and centered, choose STOP.
- If the scene is unclear or unsafe, choose STOP.

Return exactly one action token and no other text.
```

`target object not visible` 상황은 첫 번째 demo의 범위 밖으로 둔다. 초기 scene은 항상 target이 head camera field of view 안에 있도록 구성한다. 이후 search behavior를 별도 milestone으로 추가한다.

---

## 12. 핵심 closed-loop 알고리즘

```python
async def run_episode(runtime, vlm_client, cfg):
    runtime.stop()
    runtime.reset()

    previous_action = NavAction.STOP
    started_at = monotonic()

    for step_index in range(cfg.episode.max_steps):
        safety_state = read_safety_state(runtime)
        if safety_state.must_stop:
            runtime.stop()
            return EpisodeResult.failure(safety_state.reason)

        if monotonic() - started_at > cfg.episode.timeout_s:
            runtime.stop()
            return EpisodeResult.failure("episode_timeout")

        runtime.stop()
        await sleep(cfg.control.stop_settle_s)

        frame = runtime.latest_frame()

        try:
            decision = await vlm_client.decide(
                image=frame.rgb,
                instruction=cfg.task.instruction,
                previous_action=previous_action,
                timeout_s=cfg.vlm.timeout_s,
            )
        except Exception as exc:
            runtime.stop()
            record_error(exc)
            return EpisodeResult.failure("vlm_error")

        action = decision.action if decision.parse_ok else NavAction.STOP
        command = action_mapper.to_remote(action)

        recorder.record_before_action(frame, decision, command)

        runtime.send_remote(command)
        await sleep(cfg.control.action_duration_s)
        runtime.stop()

        recorder.record_after_action(runtime.latest_frame())
        previous_action = action

        if ground_truth_success(runtime):
            runtime.stop()
            return EpisodeResult.success()

        if action == NavAction.STOP and cfg.episode.stop_action_terminates:
            return EpisodeResult.from_stop_assessment(runtime)

    runtime.stop()
    return EpisodeResult.failure("max_steps")
```

### 12.1 중요한 설계 결정

- VLM inference는 locomotion controller thread와 같은 thread에서 실행하지 않는다.
- VLM timeout은 STOP으로 처리한다.
- model output을 관절 값으로 직접 사용하지 않는다.
- command를 VLM 응답 시간 동안 유지하지 않는다.
- raw output과 parsed action을 둘 다 저장한다.
- success 판정은 연구 평가용 simulator ground truth를 사용한다. 단, VLM 입력에는 target의 ground-truth 좌표를 주지 않는다.

---

## 13. 안전 및 failure handling

시뮬레이터라도 제어 루프가 runaway하지 않도록 다음 규칙을 구현한다.

### 13.1 즉시 STOP 조건

- VLM HTTP timeout
- VLM server 연결 실패
- invalid/ambiguous model output
- camera frame timeout 또는 stale frame
- NaN/Inf remote command
- command range 초과
- roll 또는 pitch가 설정 임계치를 초과
- simulation state를 일정 시간 수신하지 못함
- Ctrl+C, SIGTERM
- episode timeout
- uncaught exception

### 13.2 watchdog

별도 watchdog thread/task를 둔다.

```text
마지막 정상 high-level heartbeat가 1.0초보다 오래되면
→ remote axes를 전부 0으로 설정
→ failure reason 기록
```

### 13.3 종료 순서

```text
1. STOP 전송
2. 200~500 ms 대기
3. recorder flush
4. VLM HTTP client close
5. robot.disconnect()
6. MuJoCo viewer/camera subprocess 종료 확인
```

`finally` block에서 STOP과 disconnect를 보장한다.

---

## 14. MuJoCo scene 설계

### 14.1 첫 scene

- 평평한 바닥
- Unitree G1 초기 위치: 원점
- 빨간 상자: 로봇 기준 1.5–2.5 m 전방, 좌우 offset ±0.5 m 이내
- 장애물 없음
- 조명 고정
- 카메라 exposure/position 고정
- target은 충분히 크고 고채도의 빨간색
- 로봇이 접근해도 target과 심한 충돌이 일어나지 않도록 stop radius 설정

### 14.2 upstream cache 수정 금지

Hugging Face cache 안의 `config.yaml` 또는 scene XML을 직접 편집하지 않는다.

권장 순서:

1. upstream EnvHub scene을 프로젝트의 `assets/scenes/`로 명시적으로 복제
2. 라이선스와 원본 revision 기록
3. red target geom/body/site 추가
4. local environment adapter 또는 작은 LeRobot patch를 통해 local scene path 주입
5. patch는 최소화하고 `patches/` 또는 명시적인 subclass에 보관

현재 LeRobot `UnitreeG1.connect()`가 EnvHub ID를 직접 사용하므로 custom scene 주입은 별도 adapter가 필요할 수 있다. 먼저 upstream default scene에서 controller/camera loop를 완성한 뒤 scene customization을 진행한다.

### 14.3 평가용 ground truth

scene에 다음 이름을 고정한다.

```xml
<body name="navigation_target" ...>
  <geom name="navigation_target_geom" type="box" rgba="1 0 0 1" ... />
  <site name="navigation_target_site" ... />
</body>
```

평가 metric:

```text
distance_xy = || robot_base_xy - target_xy ||
success = distance_xy <= success_radius_m
```

권장 초기 `success_radius_m`: 0.6–0.8 m. 정확한 값은 target 크기와 G1 collision geometry를 보고 조정한다.

---

## 15. 설정 파일 예시

`configs/app.yaml`:

```yaml
project:
  name: g1-local-nav
  seed: 42

robot:
  type: unitree_g1
  is_simulation: true
  controller: GrootLocomotionController
  camera_key: global_view
  camera_port: 5555
  camera_name: head_camera
  camera_width: 640
  camera_height: 480
  camera_fps: 30

vlm:
  base_url: http://127.0.0.1:8000
  model_id: mlx-community/SmolVLM2-500M-Video-Instruct-mlx
  timeout_s: 8.0
  max_tokens: 8
  temperature: 0.0

control:
  action_duration_s: 0.30
  stop_settle_s: 0.15
  heartbeat_timeout_s: 1.0

safety:
  max_abs_roll_rad: 0.70
  max_abs_pitch_rad: 0.70
  stale_camera_s: 1.0

episode:
  timeout_s: 60.0
  max_steps: 80
  stop_action_terminates: false
  success_radius_m: 0.70

task:
  instruction: Move toward the red box and stop near it.

logging:
  root_dir: runs
  save_all_frames: true
  save_video: true
  save_raw_model_output: true
```

---

## 16. 로그 및 결과 산출물

episode마다 다음 구조로 저장한다.

```text
runs/2026-08-15T231500Z_ep0001/
├── config_resolved.yaml
├── metadata.json
├── events.jsonl
├── decisions.jsonl
├── metrics.json
├── summary.md
├── frames/
│   ├── step_000_before.jpg
│   ├── step_000_after.jpg
│   └── ...
├── video.mp4
├── stdout.log
└── stderr.log
```

`decisions.jsonl` 한 줄 예시:

```json
{
  "episode_id": "ep0001",
  "step": 4,
  "instruction": "Move toward the red box and stop near it.",
  "raw_text": "TURN_LEFT",
  "parsed_action": "TURN_LEFT",
  "parse_ok": true,
  "remote_command": {
    "remote.lx": 0.0,
    "remote.ly": 0.0,
    "remote.rx": -0.25,
    "remote.ry": 0.0
  },
  "vlm_latency_ms": 842.4,
  "camera_age_ms": 24.1,
  "roll_rad": 0.03,
  "pitch_rad": -0.02
}
```

최종 metric:

- success/failure
- failure reason
- episode duration
- number of VLM decisions
- action histogram
- invalid output count
- mean/p50/p95 VLM latency
- minimum target distance
- final target distance
- maximum absolute roll/pitch
- fall count

---

## 17. 단계별 구현 계획과 acceptance criteria

## Milestone 0 — Platform audit

작업:

- ARM64 Python 확인
- MuJoCo minimal model 실행
- `onnxruntime` import 및 trivial ONNX session 확인
- MLX와 Metal 확인
- Unitree SDK/CycloneDDS import 확인

완료 조건:

```text
python scripts/verify_platform.py
```

가 exit code 0을 반환하고 결과를 JSON으로 저장한다.

---

## Milestone 1 — Upstream G1 manual baseline

작업:

- 공식 LeRobot G1 simulation command 실행
- GROOT Balance/Walk checkpoint 다운로드
- viewer, lowstate, controller loop, camera 확인
- 가능하면 게임패드로 전진/회전

완료 조건:

- G1이 30초 이상 simulation에서 balance를 유지
- 전진, 좌회전, 우회전, 정지 각각 확인
- controller rate가 심각하게 저하되지 않음
- clean shutdown

---

## Milestone 2 — Programmatic locomotion

작업:

- `G1Runtime` 구현
- scripted sequence 실행

```text
STOP 2s
FORWARD 1s
STOP 1s
TURN_LEFT 0.5s
STOP 1s
TURN_RIGHT 0.5s
STOP
```

완료 조건:

- 게임패드 없이 움직임
- action map YAML 수정만으로 속도·부호 조정 가능
- exception 시 STOP
- unit tests 통과

---

## Milestone 3 — Camera pipeline

작업:

- head-camera frame 획득
- frame timestamp/age 계산
- JPEG 저장
- stale-frame detection

완료 조건:

- 100개의 연속 frame을 수신
- 해상도와 색상 순서 확인
- frame age를 로그에 남김
- camera publisher 종료 시 client가 무한 대기하지 않음

---

## Milestone 4 — VLM offline policy

작업:

- VLM FastAPI server 구현
- `/health`, `/v1/navigation-action` 구현
- 저장된 camera frame으로 action inference
- strict parser 구현

완료 조건:

- 로컬에서 모델 load 성공
- 20개 fixture frame에 대해 API가 모두 유효한 enum 또는 안전한 STOP을 반환
- malformed model output unit test 통과
- timeout test 통과
- raw output과 latency 기록

정확도는 첫 완료 조건이 아니다. 우선 deterministic API와 failure-safe behavior를 완성한다.

---

## Milestone 5 — Closed-loop default scene

작업:

- VLM client와 `G1Runtime` 연결
- chunked control loop 구현
- 기록 및 watchdog 구현

완료 조건:

- 하나의 명령으로 episode 실행
- 최소 10회의 sense-decide-act cycle 수행
- invalid output/timeout 시 STOP
- simulation과 VLM server가 독립적으로 재시작 가능

---

## Milestone 6 — Red-box custom scene

작업:

- target body/geom/site 추가
- 초기 pose parameterization
- ground-truth distance metric 구현
- 성공 종료 구현

완료 조건:

- target이 head camera에 보임
- 3개의 초기 좌우 offset에서 episode 실행
- 최소 한 episode에서 target 방향으로 유의미하게 접근
- 성공 여부와 최소 거리가 자동 기록

---

## Milestone 7 — Reproducibility and developer UX

작업:

- bootstrap script
- one-command run scripts
- dependency/commit pinning
- README
- diagnostics bundle
- video export

완료 조건:

```bash
make bootstrap
make vlm-server
make smoke-sim
make closed-loop
make test
```

명령이 문서와 일치한다.

---

## 18. 테스트 전략

### 18.1 unit tests

- enum parser exact match
- parser가 설명 문장을 거부하거나 단일 token만 추출하는지 확인
- ambiguous output → STOP
- unknown output → STOP
- action map 부호/범위
- command clamp
- watchdog timeout
- stale camera detection
- config validation
- metrics 계산

### 18.2 integration tests

1. **Fake VLM server + real simulator**
   - 미리 정한 행동 sequence로 G1이 움직이는지 확인
2. **Real VLM server + saved frame**
   - simulator 없이 API 확인
3. **Scripted action + camera**
   - 이동 중 camera가 갱신되는지 확인
4. **Failure injection**
   - VLM server kill
   - 10초 응답 지연
   - invalid action 응답
   - camera stream 중단
   - NaN command
5. **Full closed-loop smoke**
   - 10 step 이하의 짧은 episode

### 18.3 oracle baseline

VLM 성능 문제와 robot control 문제를 분리하기 위해 simulator ground truth 또는 간단한 red-pixel detector로 만든 **oracle high-level policy**를 테스트 전용으로 구현한다.

```text
Oracle policy 성공 + VLM policy 실패
→ perception/reasoning 문제

Oracle policy도 실패
→ action mapping/controller/scene 문제
```

Oracle은 최종 demo의 기본 policy로 사용하지 않으며 `--policy oracle` 옵션으로만 노출한다.

---

## 19. 예상 문제와 대응

### 19.1 Unitree SDK 또는 CycloneDDS가 Darwin에서 실패

증상:

- wheel/build 실패
- `ChannelFactoryInitialize` import 실패
- lowstate timeout
- loopback interface 문제

대응 순서:

1. official tested version으로 pin
2. Native arm64 Python 여부 확인
3. 최소 DDS publish/subscribe script로 분리 재현
4. LeRobot issue/commit history 확인
5. 그래도 실패하면 아래 fallback track으로 전환

#### Fallback track: DDS bypass

- MuJoCo EnvHub simulator를 직접 실행
- MuJoCo state로부터 LeRobot-compatible `lowstate` adapter 생성
- `GrootLocomotionController.run_step(remote_action, lowstate)` 직접 호출
- 반환된 lower-body target을 MuJoCo actuator에 직접 적용
- camera는 MuJoCo renderer에서 직접 획득

이 경로도 pretrained ONNX controller와 Mac 로컬 실행 조건을 유지한다. 단, upstream의 DDS bridge를 재사용하지 않으므로 별도 integration test가 필요하다.

### 19.2 VLM이 행동 token을 안정적으로 출력하지 않음

대응:

- temperature 0
- max token 8 이하
- one-token prompt
- output parser 엄격화
- invalid → STOP
- fixture 기반 prompt regression test
- 필요 시 모델 ID만 더 큰 MLX VLM으로 교체 가능하게 유지

모델 교체 때문에 robot/control 코드를 수정하면 안 된다.

### 19.3 느린 VLM 때문에 이동이 끊김

초기 버전에서는 정상이다. 안정성이 우선이다.

후속 최적화:

- 이미지 resize
- quantized MLX model
- max tokens 감소
- asynchronous prefetch
- action hysteresis
- vision feature cache가 실제 연속 프레임에 이득이 있는지 benchmark

### 19.4 로봇이 target을 지나침

- action duration 감소
- forward magnitude 감소
- STOP settle 증가
- target 근접 frame용 별도 prompt example 추가
- 성공 반경 확대가 아니라 control 값을 먼저 조정

### 19.5 좌우 회전이 반대

`action_map.yaml`의 `remote.rx` 부호만 바꾸고 regression test를 추가한다.

### 19.6 G1이 넘어짐

- remote magnitude 축소
- balance 상태에서 충분히 settle
- scene friction 확인
- viewer/control 실제 주기 로깅
- VLM 문제가 아니라 scripted action으로 먼저 재현

---

## 20. Coding Agent 작업 규칙

1. 먼저 upstream smoke test를 수행한다. 바로 전체 application을 작성하지 않는다.
2. 각 milestone이 독립적으로 실행 가능해야 한다.
3. LeRobot source를 직접 수정해야 한다면 patch를 최소화하고 이유를 문서화한다.
4. Hugging Face cache나 `site-packages`를 직접 편집하지 않는다.
5. 모델이나 controller를 학습하지 않는다.
6. CUDA 관련 dependency를 추가하지 않는다.
7. Mac에서 실행하지 못한 코드를 “작동한다”고 문서화하지 않는다.
8. 모든 실패는 STOP으로 수렴해야 한다.
9. raw observation 전체를 무분별하게 로그에 직렬화하지 않는다. 이미지와 핵심 scalar만 기록한다.
10. upstream main branch를 계속 따라가지 않는다. 최초 성공 후 SHA를 고정한다.
11. 모델 revision과 ONNX checksum을 기록한다.
12. third-party license와 notice를 보존한다.
13. 코드에는 type hints, structured logging, meaningful exceptions를 사용한다.
14. 무한 retry를 구현하지 않는다.
15. 한 번의 실행으로 관련 child process가 모두 종료되어야 한다.

---

## 21. Coding Agent가 가장 먼저 수행할 작업

아래 순서를 바꾸지 않는다.

```text
Task 1. 저장소 scaffold 생성
Task 2. verify_platform.py 작성 및 실행
Task 3. upstream LeRobot G1 manual smoke test
Task 4. 실패 시 diagnostics bundle 생성
Task 5. G1Runtime programmatic wrapper
Task 6. scripted locomotion test
Task 7. head-camera capture test
Task 8. MLX-VLM API server
Task 9. saved-frame action test
Task 10. fake-VLM closed-loop test
Task 11. real-VLM closed-loop test
Task 12. red-box scene와 metric 추가
Task 13. reproducibility/README 정리
```

Task 3이 실패하면 Task 5 이후로 넘어가지 않는다. 대신 DDS 문제인지 MuJoCo 문제인지 ONNX 문제인지 분해한다. 단, DDS 호환성 문제로 확정되면 명시적으로 Fallback track을 시작한다.

---

## 22. Definition of Done

다음 조건을 모두 만족해야 프로젝트의 첫 버전이 완료된 것으로 본다.

- [ ] Apple Silicon Mac에서 CUDA 없이 실행된다.
- [ ] MuJoCo에서 Unitree G1이 balance를 유지한다.
- [ ] pretrained Balance/Walk ONNX controller를 사용한다.
- [ ] programmatic remote action으로 전진·좌회전·우회전·정지할 수 있다.
- [ ] head camera의 최신 RGB frame을 얻을 수 있다.
- [ ] SmolVLM2가 별도 MLX 프로세스에서 실행된다.
- [ ] 자연어 지시와 이미지가 VLM endpoint에 입력된다.
- [ ] VLM 출력은 네 개의 허용된 행동 중 하나로 안전하게 파싱된다.
- [ ] invalid output, timeout, camera failure 시 STOP한다.
- [ ] red-box scene에서 closed-loop episode를 실행한다.
- [ ] episode별 frame, model output, action, latency, metric이 저장된다.
- [ ] 최소 한 번의 target 접근 demo를 영상으로 재현한다.
- [ ] 모든 dependency, upstream SHA, model revision을 기록한다.
- [ ] `make test`와 짧은 smoke test가 통과한다.
- [ ] README에 이 시스템이 end-to-end humanoid VLA가 아님을 명시한다.

---

## 23. 후속 확장 방향

첫 버전 완료 후에만 다음을 검토한다.

1. `target not visible` search behavior
2. action space에 `BACKWARD`, `STRAFE_LEFT`, `STRAFE_RIGHT` 추가
3. 연속 `[vx, vy, yaw_rate]` 출력 schema
4. 더 강한 로컬 MLX VLM 교체
5. depth camera 또는 segmentation 보조 입력
6. scene randomization
7. obstacle avoidance
8. failure case generation 및 adversarial scene search
9. quadruped Go2 backend 추가
10. 실제 legged-robot pretrained VLA 또는 remote VLA server로 high-level policy 교체

아키텍처상 `VLMClient`와 `ActionMapper` 경계를 유지하면 후속 모델을 교체해도 MuJoCo·G1·locomotion controller 계층은 그대로 재사용할 수 있다.

---

## 24. 공식 참고 자료

- LeRobot Unitree G1 guide  
  https://github.com/huggingface/lerobot/blob/main/docs/source/unitree_g1.mdx

- LeRobot Unitree G1 implementation  
  https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/unitree_g1/unitree_g1.py

- LeRobot GR00T locomotion controller implementation  
  https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/unitree_g1/gr00t_locomotion.py

- LeRobot Unitree G1 MuJoCo EnvHub  
  https://huggingface.co/lerobot/unitree-g1-mujoco

- MuJoCo official repository  
  https://github.com/google-deepmind/mujoco

- MLX-VLM  
  https://github.com/Blaizzy/mlx-vlm

- SmolVLM2 500M MLX model  
  https://huggingface.co/mlx-community/SmolVLM2-500M-Video-Instruct-mlx

- NVIDIA GR00T Whole-Body Control  
  https://github.com/NVlabs/GR00T-WholeBodyControl

---

## 25. 최종 한 문장 지시

> 먼저 Apple Silicon에서 LeRobot의 Unitree G1 MuJoCo + pretrained `GrootLocomotionController` 경로를 재현하고, 그 위에 별도 MLX-VLM 서버가 `FORWARD`, `TURN_LEFT`, `TURN_RIGHT`, `STOP` 중 하나를 선택하여 `robot.send_action()`의 remote 축으로 전달하는 안전한 chunked closed-loop navigation application을 구현하라.
