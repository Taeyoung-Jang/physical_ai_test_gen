"""P3 완료 기준 검증.

- SceneGraph → 8종 scene 피처 벡터 출력
- mutation_params와 concat 후 (16,) 벡터 확인
- 배치 처리 (N, 16) 행렬 확인

실행: .venv/bin/python tests/test_p3_feature_extractor.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from scene_generator import generate_scene, load_scene_config, load_robot_config
from feature_extractor import (
    compute_scene_features, build_feature_vector, build_feature_batch,
    describe_features, SCENE_FEATURE_NAMES, FEATURE_NAMES,
)


def main():
    print("=== P3 Feature Extractor 검증 ===\n")

    scene_cfg = load_scene_config("config/scene_gen_config.yaml")
    robot_cfg  = load_robot_config("config/robot_config.yaml")
    robot_base = robot_cfg["robot"]["base_position"]
    max_reach  = robot_cfg["robot"]["max_reach"]

    sg = generate_scene(seed=42, scene_cfg=scene_cfg, robot_cfg=robot_cfg)
    assert sg is not None

    # 1. scene features
    feats = compute_scene_features(sg, robot_base, max_reach)
    print("[1] Scene Features (8종):")
    for k in SCENE_FEATURE_NAMES:
        print(f"  {k:38s} = {feats[k]:.4f}")
    assert len(feats) == 8
    assert feats["reach_margin"] > 0, "nominal scene은 reach_margin > 0이어야 함"

    # 2. 단일 피처 벡터 (16,)
    mutation_params = {
        "target_dx": 0.03,
        "target_dy": -0.02,
        "obstacle_angle": 45.0,
        "obstacle_dist_to_target": 0.05,
        "human_zone_x": 0.50,
        "human_zone_y": 0.10,
        "tray_occupied": 0.0,
        "occlusion_ratio": 0.0,
    }
    vec = build_feature_vector(sg, mutation_params, robot_base, max_reach)
    print(f"\n[2] 단일 피처 벡터 shape={vec.shape}")
    assert vec.shape == (16,), f"예상 (16,), 실제 {vec.shape}"
    assert np.all(np.isfinite(vec)), "NaN/Inf 포함"

    # 3. 배치 (N, 16)
    import numpy as rng_np
    rng = rng_np.random.default_rng(0)
    batch_params = [
        {
            "target_dx":               float(rng.uniform(-0.1, 0.1)),
            "target_dy":               float(rng.uniform(-0.1, 0.1)),
            "obstacle_angle":          float(rng.uniform(0, 360)),
            "obstacle_dist_to_target": float(rng.uniform(0.02, 0.20)),
            "human_zone_x":            float(rng.uniform(0.25, 0.75)),
            "human_zone_y":            float(rng.uniform(-0.35, 0.35)),
            "tray_occupied":           float(rng.integers(0, 2)),
            "occlusion_ratio":         float(rng.uniform(0.0, 0.6)),
        }
        for _ in range(50)
    ]
    batch = build_feature_batch(sg, batch_params, robot_base, max_reach)
    print(f"[3] 배치 피처 행렬 shape={batch.shape}")
    assert batch.shape == (50, 16), f"예상 (50, 16), 실제 {batch.shape}"
    assert np.all(np.isfinite(batch))

    # 4. 피처 설명 출력
    print("\n[4] 피처 상세 설명:")
    describe_features(sg, mutation_params, robot_base, max_reach)

    print("\n✅ P3 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
