"""policies_vla.py — Closed-loop visuomotor 정책 (VLA) 통합.

블루프린트 7.1 3단계: 실제 VLA/LAM wrapper.

핵심 차이(아키텍처 갭):
  기존 ActionModel.predict()는 "어떤 객체를 고를지"(open-loop 객체 선택)를 한 번에 반환.
  반면 OpenVLA 같은 VLA는 매 스텝 [RGB 이미지 + 명령] → 7-DoF EE 델타를 내는 closed-loop 정책.
  → 별도의 ClosedLoopPolicy 인터페이스 + closed-loop rollout(lam_guided/closed_loop.py)이 필요.

제공:
  ClosedLoopPolicy : reset(observation, instruction) + act(rgb, instruction, robot_state)->(7,)
  StubReachPolicy  : GPU 없이 동작하는 closed-loop 휴리스틱(heuristic 객체 선택 후 servo).
                     전체 closed-loop 파이프라인을 검증하는 용도. OpenVLA가 이 자리에 drop-in.
  OpenVLAPolicy    : 실제 openvla/openvla-7b wrapper (GPU 필요, lazy import).
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

import numpy as np

from policies import MiniActionModel  # 휴리스틱 선택 재사용
from scene_graph import SceneGraph

# 7-DoF action 인덱스: [dx, dy, dz, droll, dpitch, dyaw, gripper]
ACT_DX, ACT_DY, ACT_DZ, ACT_GRIP = 0, 1, 2, 6


class ClosedLoopPolicy(Protocol):
    """매 스텝 호출되는 visuomotor 정책."""

    def reset(self, observation: SceneGraph, instruction: str) -> None: ...

    def act(self, rgb: np.ndarray, instruction: str,
            robot_state: dict[str, Any]) -> np.ndarray:
        """반환: shape (7,) = [dx, dy, dz, droll, dpitch, dyaw, gripper].
        dx~dz 는 EE 델타(단위 방향, rollout 이 스케일), gripper 는 [0=open,1=close]."""
        ...


# ---------------------------------------------------------------------------
# Stub: GPU 없이 closed-loop 전 과정을 검증
# ---------------------------------------------------------------------------

class StubReachPolicy:
    """휴리스틱으로 객체 하나를 고른 뒤 그쪽으로 EE를 servo 하는 closed-loop 정책.

    MiniActionModel 의 점수화를 재사용해 첫 관측에서 목표 객체를 정한다(유사 distractor가
    들어오면 wrong object 로 향함). 이후 매 스텝 목표 방향으로 정규화 델타를 낸다.
    OpenVLA 가 들어오기 전, closed-loop rollout/oracle 전체를 시험하기 위한 stand-in.
    """

    name = "stub_reach_policy"

    def __init__(self, cfg: Optional[dict] = None, seed: int = 0):
        self._mini = MiniActionModel(cfg=cfg, seed=seed)
        self.grasp_thresh = (cfg or {}).get("grasp_thresh", 0.03)  # m
        self._goal: Optional[np.ndarray] = None
        self._goal_id: Optional[str] = None

    def reset(self, observation: SceneGraph, instruction: str) -> None:
        rs = {"base": [0.0, 0.0, 0.0], "max_reach": 0.855}
        plan = self._mini.predict(instruction, observation, rs)
        sel = observation.get_object(plan.selected_obj_id)
        self._goal_id = plan.selected_obj_id
        self._goal = np.array(sel.position) if sel is not None else None

    def act(self, rgb, instruction, robot_state) -> np.ndarray:
        a = np.zeros(7, dtype=float)
        if self._goal is None:
            return a
        ee = np.array(robot_state["ee_pos"])
        # grasp pose: 목표 위쪽으로 접근하다 가까워지면 하강
        delta = self._goal - ee
        dist = float(np.linalg.norm(delta))
        a[ACT_DX:ACT_DZ + 1] = delta / (dist + 1e-9)   # 단위 방향
        a[ACT_GRIP] = 1.0 if dist < self.grasp_thresh else 0.0
        return a


# ---------------------------------------------------------------------------
# 실제 OpenVLA wrapper (GPU 필요)
# ---------------------------------------------------------------------------

def resolve_device_dtype(device: str = "auto"):
    """실행 환경에 맞는 (device, torch_dtype) 을 고른다.

    cuda → bf16, Apple Silicon MPS → fp32, cpu → fp32.
    MPS는 float64 미지원이므로 fp32 사용 (fp16보다 안정적).
    flash-attn 은 CUDA 전용이므로 어디서나 'eager' attention 을 쓴다.
    """
    import torch
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda:0"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    if device.startswith("cuda"):
        dtype = torch.bfloat16
    else:
        # MPS + CPU 모두 float32. MPS는 float64 미지원이므로 fp32로 고정.
        dtype = torch.float32
    return device, dtype


def _patch_float64_to_float32(model) -> None:
    """모델 내 float64 파라미터·버퍼를 float32로 변환한다.

    transformers 일부 구현(RoPE inv_freq 등)이 CPU 로딩 시 float64를 생성한다.
    MPS는 float64를 지원하지 않으므로 .to(device) 전에 변환해야 한다.
    """
    import torch
    for name, buf in list(model.named_buffers()):
        if buf.dtype == torch.float64:
            parts = name.split(".")
            obj = model
            for p in parts[:-1]:
                obj = getattr(obj, p)
            setattr(obj, parts[-1], buf.to(torch.float32))
    for param in model.parameters():
        if param.data.dtype == torch.float64:
            param.data = param.data.to(torch.float32)


class OpenVLAPolicy:
    """openvla/openvla-7b wrapper. device 자동감지 (cuda / Apple Silicon MPS / cpu).

    Apple Silicon (M1~M4): MPS + float32 로 동작한다.
    MPS는 float64 미지원이므로 모델 로드 후 float64 버퍼를 float32로 패치한다.
    attention_mask 는 MPS에서 불필요하므로 제거한다.

    flash_attention_2(CUDA 전용)는 쓰지 않고 eager attention 만 사용.
    모델은 실행 시 lazy 로딩(import 시 불필요).

    embodiment gap: action 은 학습 로봇(WidowX 등) 좌표계 → frame_transform / pos_scale 로 보정.
    """

    name = "openvla"

    def __init__(self, model_id: str = "openvla/openvla-7b",
                 unnorm_key: str = "bridge_orig", device: str = "auto",
                 pos_scale: float = 1.0, frame_transform: Optional[np.ndarray] = None):
        self.model_id = model_id
        self.unnorm_key = unnorm_key
        self.device = device
        self.pos_scale = pos_scale
        self.frame_transform = (np.eye(3) if frame_transform is None
                                else np.array(frame_transform))
        self._model = None
        self._processor = None
        self._dtype = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForVision2Seq, AutoProcessor
        self._torch = torch
        self.device, self._dtype = resolve_device_dtype(self.device)

        self._processor = AutoProcessor.from_pretrained(
            self.model_id, trust_remote_code=True)
        # CPU에 먼저 로드한 뒤 float64 버퍼를 패치하고 device로 이동
        self._model = AutoModelForVision2Seq.from_pretrained(
            self.model_id, torch_dtype=self._dtype,
            attn_implementation="eager",
            low_cpu_mem_usage=True, trust_remote_code=True)
        if self.device == "mps":
            _patch_float64_to_float32(self._model)
        self._model = self._model.to(self.device)
        print(f"[OpenVLA] loaded on device={self.device} dtype={self._dtype}")

    def reset(self, observation: SceneGraph, instruction: str) -> None:
        pass  # OpenVLA 는 frame 단위 stateless

    def act(self, rgb: np.ndarray, instruction: str,
            robot_state: dict[str, Any]) -> np.ndarray:
        self._ensure_loaded()
        import torch
        from PIL import Image
        img = Image.fromarray(np.asarray(rgb, dtype=np.uint8))
        prompt = f"In: What action should the robot take to {instruction}?\nOut:"
        raw_inputs = self._processor(prompt, img)
        # 정수형(input_ids 등)은 dtype 변환 없이 device만 이동,
        # 부동소수형(pixel_values 등)은 model dtype으로 변환
        inputs = {
            k: (v.to(self.device, dtype=self._dtype)
                if isinstance(v, torch.Tensor) and v.is_floating_point()
                else v.to(self.device) if isinstance(v, torch.Tensor)
                else v)
            for k, v in raw_inputs.items()
        }
        inputs.pop("attention_mask", None)  # MPS에서 불필요, CPU에서도 제거
        raw = self._model.predict_action(
            **inputs, unnorm_key=self.unnorm_key, do_sample=False, use_cache=False)
        action = np.asarray(raw, dtype=float).reshape(-1)  # (7,)
        action[0:3] = self.pos_scale * (self.frame_transform @ action[0:3])
        return action


# ---------------------------------------------------------------------------
# 팩토리
# ---------------------------------------------------------------------------

def make_closed_loop_policy(kind: str, cfg: Optional[dict] = None,
                            seed: int = 0) -> ClosedLoopPolicy:
    cfg = cfg or {}
    if kind in ("stub", "stub_reach"):
        return StubReachPolicy(cfg=cfg, seed=seed)
    if kind in ("openvla", "vla"):
        return OpenVLAPolicy(
            model_id=cfg.get("model_id", "openvla/openvla-7b"),
            unnorm_key=cfg.get("unnorm_key", "bridge_orig"),
            device=cfg.get("device", "auto"),
            pos_scale=cfg.get("pos_scale", 1.0),
            frame_transform=cfg.get("frame_transform"),
        )
    raise ValueError(f"unknown closed-loop policy: {kind}")
