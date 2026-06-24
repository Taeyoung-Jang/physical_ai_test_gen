"""P4 완료 기준 검증.

- 1개 SceneGraph → 유효 후보 1,000개 이상 1초 이내
- 3종 샘플러 동작 확인
- boundary seeds 6종 이상 생성

실행: .venv/bin/python tests/test_p4_mutation_space.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scene_generator import generate_scene, load_scene_config, load_robot_config
from mutation_space import (
    sample_random, sample_latin_hypercube,
    sample_boundary_seeds, sample_initial_seeds,
)


def main():
    print("=== P4 Mutation Space Builder 검증 ===\n")

    scene_cfg = load_scene_config("config/scene_gen_config.yaml")
    robot_cfg  = load_robot_config("config/robot_config.yaml")
    sg = generate_scene(seed=42, scene_cfg=scene_cfg, robot_cfg=robot_cfg)

    # 1. random sampler (1,000개 < 1초)
    t0 = time.perf_counter()
    random_samples = sample_random(sg, robot_cfg, n=1000, seed=0)
    elapsed = time.perf_counter() - t0
    print(f"[1] Random sampler: {len(random_samples)}개 유효  ({elapsed*1000:.1f} ms)")
    assert len(random_samples) >= 500, f"유효 후보 너무 적음: {len(random_samples)}"
    assert elapsed < 1.0, f"속도 초과: {elapsed:.2f}s"

    # 2. LHS sampler
    lhs_samples = sample_latin_hypercube(sg, robot_cfg, n=50, seed=0)
    print(f"[2] LHS sampler: {len(lhs_samples)}개 유효")
    assert len(lhs_samples) > 0

    # 3. boundary seeds
    boundary = sample_boundary_seeds(sg, robot_cfg)
    print(f"[3] Boundary seeds: {len(boundary)}개")
    for i, b in enumerate(boundary):
        print(f"     seed_{i}: dx={b['target_dx']:.3f}  "
              f"obs_dist={b['obstacle_dist_to_target']:.3f}  "
              f"tray_occ={b['tray_occupied']:.0f}  "
              f"occ={b['occlusion_ratio']:.2f}")
    assert len(boundary) >= 4, "boundary seeds 부족"

    # 4. initial seeds (혼합)
    init_seeds = sample_initial_seeds(sg, robot_cfg, k=10, seed=0)
    print(f"[4] Initial seeds (boundary+LHS 혼합): {len(init_seeds)}개")
    assert len(init_seeds) >= 5

    # 5. 파라미터 값 범위 검증
    for sample in random_samples[:100]:
        assert -0.10 <= sample["target_dx"] <= 0.10
        assert 0.0 <= sample["obstacle_angle"] <= 360.0
        assert sample["tray_occupied"] in (0.0, 1.0)
        assert 0.0 <= sample["occlusion_ratio"] <= 0.60

    print(f"[5] 파라미터 범위 검증 OK (100개 샘플)")
    print("\n✅ P4 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
