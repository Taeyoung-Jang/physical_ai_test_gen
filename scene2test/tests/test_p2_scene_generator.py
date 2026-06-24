"""P2 완료 기준 검증 테스트.

- generate_library(20) 실행 → 20개 SceneGraph JSON 저장
- 모든 scene이 is_valid_base_scene 통과
- 1개 SceneGraph에서 is_valid_mutation 1,000개 필터 < 1초

실행: .venv/bin/python tests/test_p2_scene_generator.py
"""
import sys, os, time, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scene_generator import generate_library, generate_scene, load_scene_config, load_robot_config
from validity import is_valid_base_scene, is_valid_mutation, filter_mutation_batch
from scene_graph import SceneGraph


def test_single_scene():
    scene_cfg = load_scene_config("config/scene_gen_config.yaml")
    robot_cfg  = load_robot_config("config/robot_config.yaml")
    sg = generate_scene(seed=42, scene_cfg=scene_cfg, robot_cfg=robot_cfg)
    assert sg is not None, "seed=42로 scene 생성 실패"
    assert sg.target() is not None
    assert sg.destination() is not None
    assert is_valid_base_scene(sg, robot_cfg, verbose=True)
    print(f"  단일 scene OK: {sg.scene_id}  "
          f"objects={len(sg.objects)}  relations={len(sg.relations)}")
    return sg


def test_library(n=20):
    out_dir = "data/scene_library_test"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)

    scene_cfg = load_scene_config("config/scene_gen_config.yaml")
    robot_cfg  = load_robot_config("config/robot_config.yaml")

    scenes = generate_library(n, out_dir, scene_cfg, robot_cfg)
    assert len(scenes) == n, f"생성된 scene 수 부족: {len(scenes)}/{n}"

    # 저장된 JSON 파일 수 확인
    files = [f for f in os.listdir(out_dir) if f.endswith(".json")]
    assert len(files) == n, f"저장된 JSON 파일 수 불일치: {len(files)}"

    # 모든 scene round-trip + validity
    for f in files:
        sg = SceneGraph.load(os.path.join(out_dir, f))
        assert is_valid_base_scene(sg, robot_cfg), f"{f}: validity 실패"

    shutil.rmtree(out_dir)
    print(f"  라이브러리 {n}개 생성 + validity 전부 통과")


def test_mutation_filter_speed(sg: SceneGraph):
    robot_cfg = load_robot_config("config/robot_config.yaml")

    # 1,000개 랜덤 mutation 후보 생성
    import numpy as np
    rng = np.random.default_rng(0)
    bounds = sg.support_surfaces[0].bounds

    candidates = []
    for _ in range(1000):
        candidates.append({
            "target_dx":               float(rng.uniform(-0.10, 0.10)),
            "target_dy":               float(rng.uniform(-0.10, 0.10)),
            "obstacle_angle":          float(rng.uniform(0, 360)),
            "obstacle_dist_to_target": float(rng.uniform(0.02, 0.20)),
            "human_zone_x":            float(rng.uniform(bounds["x"][0], bounds["x"][1])),
            "human_zone_y":            float(rng.uniform(bounds["y"][0], bounds["y"][1])),
            "tray_occupied":           float(rng.integers(0, 2)),
            "occlusion_ratio":         float(rng.uniform(0.0, 0.6)),
        })

    t0 = time.perf_counter()
    valid = filter_mutation_batch(sg, candidates, robot_cfg)
    elapsed = time.perf_counter() - t0

    print(f"  mutation 필터: 1,000개 → {len(valid)}개 유효  ({elapsed*1000:.1f} ms)")
    assert elapsed < 1.0, f"필터 속도 초과: {elapsed:.2f}s (목표 < 1s)"
    assert len(valid) > 100, f"유효 후보 너무 적음: {len(valid)}"


def main():
    print("=== P2 Scene Generator + Validity 검증 ===\n")

    print("[1] 단일 scene 생성")
    sg = test_single_scene()

    print("\n[2] 라이브러리 20개 생성")
    test_library(20)

    print("\n[3] Mutation 필터 속도 (1,000개 < 1초)")
    test_mutation_filter_speed(sg)

    print("\n✅ P2 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
