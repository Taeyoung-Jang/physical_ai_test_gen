"""tools/gen3d_asset.py — 3D object generation 데모 CLI (Shap-E) + default 폴백.

텍스트 프롬프트로 3D 메쉬 asset 을 생성해 asset bank(index.json)에 등록하고,
씬에 배치한 스냅샷을 저장한다. 3D 생성 모델이 없거나 실패하면 procedural default 로 폴백.

  # 실제 생성 (gen3d 설치 필요. Apple Silicon은 자동 CPU — float64 때문)
  PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py \
      --prompt "a red soda can" --asset-id gen3d_red_can --family semantic_distractor --steps 24

  # 모델 없이 (폴백 확인)
  PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py --no-model --family semantic_distractor
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p

import scene_builder
from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.asset_gen import acquire_asset, make_generator
from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface

INDEX = "data/generated_assets/index.json"


def parse_args():
    ap = argparse.ArgumentParser(description="3D object generation 데모")
    ap.add_argument("--prompt", default="a red soda can")
    ap.add_argument("--asset-id", default="gen3d_demo")
    ap.add_argument("--family", default="semantic_distractor")
    ap.add_argument("--role", default="distractor")
    ap.add_argument("--tags", default="red,can")
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--device", default="auto", help="auto | cpu | cuda:0 (Shap-E는 MPS 미지원→CPU)")
    ap.add_argument("--no-model", action="store_true", help="생성 모델 미사용(폴백 확인)")
    ap.add_argument("--output", default="reports/gen3d_asset.png")
    return ap.parse_args()


def main():
    args = parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    bank = GeneratedAssetBank.default(INDEX)
    generator = None if args.no_model else make_generator(
        "shap_e", num_inference_steps=args.steps, device=args.device)
    if generator is not None and not generator.available():
        print("[gen3d] 생성 모델 의존성 없음 → default 폴백 (uv sync --extra gen3d 로 설치)")

    spec = {
        "prompt": args.prompt, "asset_id": args.asset_id, "role": args.role,
        "semantic_tags": args.tags.split(","), "family_affinity": [args.family],
        "visual_similarity_to_target": 0.85, "size": [0.066, 0.066, 0.10],
    }
    print(f"\n=== 3D Asset Acquire ===\n  prompt=\"{args.prompt}\"  family={args.family}\n")
    asset_id = acquire_asset(bank, args.family, spec=spec, generator=generator,
                             index_path=INDEX)
    asset = bank.get(asset_id)
    print(f"  → asset_id={asset_id}  source={asset.source}  shape={asset.shape}")
    if asset.mesh_path:
        print(f"  mesh={asset.mesh_path}")
    print(f"  size(AABB)={[round(x, 3) for x in asset.size]}")

    # 씬에 배치해 스냅샷
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid
    node = asset.to_object_node("gen_obj", [0.56, 0.09, 0.0])
    sg = SceneGraph("gen3d_demo",
        support_surfaces=[SupportSurface("t", "plane", 0.0,
                                         {"x": [0.3, 0.8], "y": [-0.35, 0.35]})],
        objects=[ObjectNode("target_0", Role.TARGET, [0.46, -0.04, 0.05],
                            [0.066, 0.066, 0.10], True, "can"), node])
    scene_builder.reset_simulation()
    scene_builder.load_scene(sg)
    view = p.computeViewMatrixFromYawPitchRoll([0.52, 0.0, 0.06], 0.65, 55, -22, 0, 2,
                                               physicsClientId=cid)
    proj = p.computeProjectionMatrixFOV(60, 1.0, 0.01, 10, physicsClientId=cid)
    _, _, rgba, _, _ = p.getCameraImage(520, 520, viewMatrix=view, projectionMatrix=proj,
                                        renderer=p.ER_TINY_RENDERER, physicsClientId=cid)
    img = np.array(rgba, np.uint8).reshape(520, 520, 4)[:, :, :3]
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    import imageio
    imageio.imwrite(args.output, img)
    print(f"\n  스냅샷 저장: {args.output}")
    p.disconnect(physicsClientId=cid)
    print("✓ 완료")


if __name__ == "__main__":
    main()
