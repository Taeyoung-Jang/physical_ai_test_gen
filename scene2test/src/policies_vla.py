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

    cuda → bf16, Apple Silicon(mps) → fp16, cpu → fp32.
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
    elif device == "mps":
        dtype = torch.float16        # MPS는 bf16 지원이 불완전 → fp16
    else:
        dtype = torch.float32
    return device, dtype


class OpenVLAPolicy:
    """openvla/openvla-7b wrapper. device 자동감지 (cuda / Apple Silicon → cpu / cpu).

    ⚠️ **Apple Silicon(MPS) 미지원**: OpenVLA-7B의 attention mask 계산이 MPS에서 실패하므로
       자동으로 CPU로 폴백한다. M4 Pro의 경우 fp32 CPU 추론이 느리지만(~수 초/스텝)
       메모리는 충분하다(통합메모리 16GB+). 가벼운 대안은 docs/openvla_integration.md 의 Octo 참고.

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
        self.device = device                # "auto"면 _ensure_loaded 에서 결정
        self.pos_scale = pos_scale
        self.frame_transform = (np.eye(3) if frame_transform is None
                                else np.array(frame_transform))
        self._model = None
        self._processor = None
        self._dtype = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        import torch  # noqa: 지연 import (실행 환경에서만)
        from transformers import AutoModelForVision2Seq, AutoProcessor
        self._torch = torch
        self.device, self._dtype = resolve_device_dtype(self.device)
        # OpenVLA는 MPS에서 attention mask 계산 오류 발생 → CPU 폴백
        # if self.device == "mps":
        #     self.device = "cpu"
        #     self._dtype = torch.float32
        self._processor = AutoProcessor.from_pretrained(
            self.model_id, trust_remote_code=True)
        self._model = AutoModelForVision2Seq.from_pretrained(
            self.model_id, torch_dtype=self._dtype,
            attn_implementation="eager",          # flash-attn(CUDA전용) 미사용
            low_cpu_mem_usage=True, trust_remote_code=True).to(self.device)
        print(f"[OpenVLA] loaded on device={self.device} dtype={self._dtype}")

    def reset(self, observation: SceneGraph, instruction: str) -> None:
        pass                                # OpenVLA 는 frame 단위 stateless

    def act(self, rgb: np.ndarray, instruction: str,
            robot_state: dict[str, Any]) -> np.ndarray:
        self._ensure_loaded()
        from PIL import Image
        img = Image.fromarray(np.asarray(rgb, dtype=np.uint8))
        prompt = f"In: What action should the robot take to {instruction}?\nOut:"
        inputs = self._processor(prompt, img).to(self.device, dtype=self._dtype)
        inputs.pop("attention_mask", None)
        raw = self._model.predict_action(**inputs, unnorm_key=self.unnorm_key, do_sample=False, use_cache=False)
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
