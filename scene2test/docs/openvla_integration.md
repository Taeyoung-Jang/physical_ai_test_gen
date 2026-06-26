# OpenVLA 실제 통합 가이드

이 시스템은 **정책을 테스트하는 프레임워크**이며, 테스트 대상 정책은 교체 가능하다.
RuleLAMProxy → MiniActionModel(휴리스틱) → **실제 VLA(OpenVLA)** 순서로 강화한다.

## 아키텍처: 왜 closed-loop 경로가 따로 필요한가

| | 기존 `ActionModel` | VLA(OpenVLA) |
|---|---|---|
| 인터페이스 | `predict()` 한 번 → 객체 선택(open-loop) | 매 스텝 `act(rgb, instr)` → 7-DoF 델타(closed-loop) |
| 입력 | SceneGraph | **RGB 이미지** + 명령 |
| 출력 | `selected_obj_id` + subgoal | `(dx,dy,dz,droll,dpitch,dyaw,gripper)` |

그래서 별도 인터페이스/실행 경로를 추가했다 (기존 코드 무손상):
- `src/policies_vla.py` — `ClosedLoopPolicy` Protocol, `StubReachPolicy`(GPU-free), `OpenVLAPolicy`(GPU)
- `src/lam_guided/closed_loop.py` — `render_rgb`, `run_closed_loop_rollout`(렌더→act→IK 델타→step), `infer_selected_object`(post-hoc 선택 추정)

산출 `RolloutTrace` 는 기존과 동일 스키마 → **PolicyOracle/Physical 체크가 그대로 동작**한다.
즉 OpenVLA 는 `ClosedLoopPolicy` 자리에 **drop-in** 된다.

## GPU 없이 검증된 것 (이 저장소)

```bash
# stub 정책으로 closed-loop 전 과정 데모 (GPU 불필요)
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json --policy stub \
    --insert distractor_red_can --gif

# 검증 테스트 (render_rgb, closed-loop, wrong-grounding 재현, OpenVLA lazy 생성)
PYBULLET_MODE=DIRECT uv run python tests/test_p12_vla_closed_loop.py
```
RGB 관측(224×224)·closed-loop 구동·post-hoc 객체 추정·오라클 호환이 모두 동작한다.

## 설치 (환경별)

의존성은 optional extra `vla` 로 분리되어 있다(코어 프로젝트에 영향 없음).

### Apple Silicon (M1~M4, 이 프로젝트 환경)
```bash
uv sync --extra vla       # torch는 macOS arm64에서 자동으로 MPS(Metal) 빌드
```
- ⚠️ **OpenVLA-7B는 Apple Silicon(MPS) 미지원**: attention mask 계산 오류 발생 → **자동으로 CPU로 폴백**.
  - 초기 감지는 MPS가 되지만, 모델 로드 시 CPU(fp32)로 강제 전환.
  - 결과: 느리지만(~수 초/스텝) 메모리 충분(통합메모리 16GB+)하면 동작.
- 확인: `uv run python -c "import torch; print(torch.backends.mps.is_available())"` → `True` (감지만 됨, 실제 사용 안 함)
- transformers/timm/tokenizers 는 OpenVLA 호환 버전으로 고정됨(4.40.1 / 0.9.10 / 0.19.1).

### CUDA GPU
```bash
uv sync --extra vla       # 또는 OpenVLA 공식 requirements-min.txt
```
- `device="auto"` → cuda 감지 + bf16. flash-attn 은 선택(미설치여도 eager로 동작).

> 모델 `openvla/openvla-7b` (~15GB)은 **최초 실행 시 자동 다운로드**된다.

### ⚠️ Apple Silicon 성능 현실 (정직하게)
- OpenVLA-7B는 7B 파라미터 → fp16 기준 **~14GB 통합메모리** 사용(24GB 모델은 빠듯, 48GB 권장).
- MPS 추론은 느리다(**스텝당 수 초**). 40스텝 rollout = 수 분 가능.
- `trust_remote_code` 모델이 MPS 미지원 연산을 CPU로 폴백할 수 있어 더 느려지거나 오류가 날 수 있음.
- **첫 1회 추론으로 동작/속도부터 확인**하길 권장. 가벼운 대안은 아래 Octo.

### 가벼운 대안: Octo (Apple Silicon에 더 현실적)
[Octo](https://github.com/octo-models/octo) 는 27M~93M 파라미터 transformer 정책(JAX)이라
M4 Pro에서 훨씬 빠르고 메모리 부담이 작다. `ClosedLoopPolicy` 인터페이스(`reset`/`act`)만
구현하면 OpenVLAPolicy 자리에 동일하게 drop-in 된다(`OctoPolicy` 추가 시 같은 rollout 사용).

## 실행
```bash
# device=auto (Apple Silicon이면 자동 mps)
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json --policy openvla \
    --instruction "pick up the red can" --unnorm-key bridge_orig --pos-scale 1.0
# 명시도 가능: --device mps | cuda:0 | cpu
```
`OpenVLAPolicy.act()` 가 매 스텝 수행하는 것 (이미 구현됨):
```python
prompt = f"In: What action should the robot take to {instruction}?\nOut:"
inputs = processor(prompt, Image.fromarray(rgb)).to("cuda:0", dtype=bfloat16)
action = vla.predict_action(**inputs, unnorm_key="bridge_orig", do_sample=False)  # (7,)
```

### 3. 반드시 보정해야 하는 것 (embodiment gap)

OpenVLA action 은 학습 데이터(Bridge=WidowX 등)의 **좌표계·스케일·gripper 규약**이다.
Franka 작업공간에 그대로 쓰면 안 맞는다. `OpenVLAPolicy` 의 보정 훅:

| 항목 | 파라미터 | 설명 |
|---|---|---|
| 위치 스케일 | `--pos-scale` / `pos_scale` | 델타 크기 보정 (m 단위 맞춤) |
| 프레임 회전 | `frame_transform` (3×3) | 학습 카메라/로봇 프레임 → Franka 프레임 |
| unnorm 통계 | `--unnorm-key` | 데이터셋별 역정규화 키 (`bridge_orig` 등) |
| gripper 규약 | `closed_loop.py` 의 `a[6] > 0.5` 임계 | OpenVLA gripper 값 방향 확인 후 조정 |
| 카메라 | `render_rgb` 의 yaw/pitch/distance | OpenVLA 가 기대하는 3인칭 시점에 근접하게 |

> 현실적으로 zero-shot 성능은 낮을 수 있고, 대상 로봇/카메라로 **fine-tuning** 하면 크게 개선된다.
> 본 프레임워크의 목적은 *그 정책이 어떤 3D 조건에서 실패하는지 자동 탐색*하는 것이므로,
> zero-shot이든 fine-tuned든 동일한 LAM-Guided 루프로 취약성을 프로파일링할 수 있다.

### 4. LAM-Guided 루프에 연결 (선택, 다음 단계)

현재 `lam_guided_loop.py` 는 open-loop `run_policy_rollout` 을 쓴다. closed-loop 정책으로
전체 루프를 돌리려면, 루프의 `_run_case`/`_probe` 에서 `run_closed_loop_rollout` 을 호출하는
분기를 추가하면 된다(인터페이스·RolloutTrace 동일하므로 BehaviorEncoder/Profiler/Generator는 불변).
이 연결은 GPU 환경에서 OpenVLA 추론 비용(스텝당 1회)을 고려해 batch/스텝 수를 조정한다.

## 요약

- 골격·관측·실행·오라클 **모두 GPU 없이 검증됨** (stub).
- OpenVLA 는 `--policy openvla` 로 **drop-in**, 실제 추론만 GPU에서.
- 남은 실무 작업은 **embodiment 보정**(스케일/프레임/gripper)과 선택적 **fine-tuning**.
