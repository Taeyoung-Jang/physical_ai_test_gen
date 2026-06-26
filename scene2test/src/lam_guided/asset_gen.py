"""asset_gen.py — 3D object generation (선택) + default 폴백.

블루프린트 14장 2~3단계. 텍스트→3D 생성 모델(Shap-E)로 distractor/occluder 메쉬를
오프라인 생성하고 asset bank 에 등록한다. **모델이 없거나 실패하면 procedural default
객체로 폴백**한다(사용자 요구: "3d 생성 모델이 없다면 default object 이용").

  Asset3DGenerator : available() / generate(spec) 인터페이스
  ShapEGenerator   : diffusers Shap-E (Apple Silicon MPS / CUDA / CPU). 선택 설치.
  NullGenerator    : 항상 available()=False (명시적 '모델 없음')
  acquire_asset()  : 생성 시도 → 실패/불가 시 default 반환
"""
from __future__ import annotations

import os
from typing import Any, Optional, Protocol

from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.types import GeneratedAsset
from scene_graph import Role

MESH_DIR = "data/generated_assets/meshes"


class Asset3DGenerator(Protocol):
    def available(self) -> bool: ...
    def generate(self, spec: dict[str, Any]) -> Optional[GeneratedAsset]: ...


# ---------------------------------------------------------------------------
# Null (모델 없음)
# ---------------------------------------------------------------------------

class NullGenerator:
    name = "null"

    def available(self) -> bool:
        return False

    def generate(self, spec):
        return None


# ---------------------------------------------------------------------------
# Shap-E (text → 3D mesh). diffusers + trimesh 필요(선택 설치).
# ---------------------------------------------------------------------------

class ShapEGenerator:
    """openai/shap-e 로 텍스트→메쉬 생성. Apple Silicon(MPS)/CUDA/CPU 자동.

    설치:  uv sync --extra gen3d   (diffusers, trimesh; torch 는 --extra vla)
    주의:  M4 Pro 에서 추론은 느릴 수 있다(수십 초~분). 실패하면 acquire_asset 이 default 로 폴백.
    """

    name = "shap_e"

    def __init__(self, num_inference_steps: int = 32, guidance_scale: float = 15.0,
                 frame_size: int = 192, device: str = "auto", seed: int = 0):
        self.steps = num_inference_steps
        self.guidance = guidance_scale
        self.frame_size = frame_size
        self.device = device
        self.seed = seed
        self._pipe = None

    def available(self) -> bool:
        try:
            import diffusers  # noqa: F401
            import torch  # noqa: F401
            import trimesh  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_pipe(self):
        if self._pipe is not None:
            return
        import torch
        from diffusers import ShapEPipeline

        from policies_vla import resolve_device_dtype
        dev, dtype = resolve_device_dtype(self.device)
        # Shap-E 렌더러는 float64 를 쓰는데 Apple MPS 가 미지원 → mps면 CPU로 폴백.
        if dev == "mps":
            dev, dtype = "cpu", torch.float32
        self._device = dev
        self._pipe = ShapEPipeline.from_pretrained(
            "openai/shap-e", torch_dtype=dtype).to(dev)
        self._torch = torch

    def generate(self, spec: dict[str, Any]) -> Optional[GeneratedAsset]:
        if not self.available():
            return None
        try:
            return self._generate(spec)
        except Exception as e:
            print(f"[ShapEGenerator] 생성 실패 → default 폴백: {e}")
            return None

    def _generate(self, spec) -> GeneratedAsset:
        import numpy as np
        import trimesh
        from diffusers.utils import export_to_ply
        self._ensure_pipe()

        prompt = spec["prompt"]
        asset_id = spec.get("asset_id", "gen3d_" + prompt.replace(" ", "_")[:24])
        out_dir = os.path.join(MESH_DIR, asset_id)
        os.makedirs(out_dir, exist_ok=True)
        ply_path = os.path.join(out_dir, "model.ply")
        obj_path = os.path.join(out_dir, "model.obj")

        gen = self._torch.Generator(device="cpu").manual_seed(self.seed)
        result = self._pipe(prompt, generator=gen, guidance_scale=self.guidance,
                            num_inference_steps=self.steps, frame_size=self.frame_size,
                            output_type="mesh").images
        export_to_ply(result[0], ply_path)

        # 메쉬 정규화: 원점 중심 + 목표 크기로 스케일, OBJ 저장
        mesh = trimesh.load(ply_path, force="mesh")
        mesh.apply_translation(-mesh.bounding_box.centroid)
        target = np.array(spec.get("size", [0.07, 0.07, 0.10]))
        ext = mesh.bounding_box.extents
        scale = float(np.min(target / np.maximum(ext, 1e-6)))
        mesh.apply_scale(scale)
        # 바닥이 z=0 에 닿도록 올림
        mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
        mesh.export(obj_path)
        aabb = mesh.bounding_box.extents.tolist()

        return GeneratedAsset(
            asset_id=asset_id, role=spec.get("role", Role.DISTRACTOR), shape="mesh",
            size=[float(aabb[0]), float(aabb[1]), float(aabb[2])],
            semantic_tags=list(spec.get("semantic_tags", [])),
            visual_similarity_to_target=spec.get("visual_similarity_to_target", 0.7),
            family_affinity=list(spec.get("family_affinity", [])),
            mass=spec.get("mass", 0.1), mesh_path=obj_path, source="shap_e",
        )


# ---------------------------------------------------------------------------
# 팩토리 + 폴백 acquire
# ---------------------------------------------------------------------------

def make_generator(kind: str = "shap_e", **kw) -> Asset3DGenerator:
    if kind in ("none", "null"):
        return NullGenerator()
    if kind in ("shap_e", "shape", "shap-e"):
        return ShapEGenerator(**kw)
    raise ValueError(f"unknown 3D generator: {kind}")


def acquire_asset(bank: GeneratedAssetBank, family: str,
                  spec: Optional[dict] = None,
                  generator: Optional[Asset3DGenerator] = None,
                  index_path: Optional[str] = None) -> str:
    """3D 생성 시도 → 불가/실패 시 family default(procedural)로 폴백, asset_id 반환.

    생성에 성공하면 bank 에 등록하고 index.json 갱신(index_path 주어진 경우).
    """
    if generator is not None and generator.available() and spec is not None:
        spec = {**spec, "family_affinity": spec.get("family_affinity", [family])}
        asset = generator.generate(spec)
        if asset is not None:
            bank._assets[asset.asset_id] = asset       # 등록
            if index_path:
                bank.save_index(index_path)
            return asset.asset_id

    # 폴백: 이 family 의 default procedural asset
    cands = bank.query(family=family)
    if cands:
        return cands[0].asset_id
    # 최후 폴백: 아무 distractor
    alld = bank.query(role=Role.DISTRACTOR)
    return alld[0].asset_id if alld else bank.all()[0].asset_id
