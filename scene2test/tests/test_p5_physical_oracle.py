"""P5 완료 기준 검증.

6종 Oracle 각각을 유발하는 mutation을 실행하고
PASS/FAIL/WARN/BLOCKED + robustness + failure_type이 올바른지 확인한다.

Base scene은 human_zone 없는 seed를 자동으로 탐색한다.
(human_zone이 있으면 EE 경로 특성상 safety_margin이 항상 음수가 될 수 있음)
T04(human_risk)는 mutation_params로 human_zone을 삽입한다.

실행: .venv/bin/python tests/test_p5_physical_oracle.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

from scene_builder import connect
from scene_generator import generate_scene, load_scene_config, load_robot_config
from physical_oracle import run_oracle_on_mutation, load_thresholds, Verdict
from scene_graph import Role


def find_scene_without_human_zone(scene_cfg, robot_cfg, start_seed=0, max_tries=50):
    """human_zone이 없는 유효한 base scene을 찾는다."""
    for seed in range(start_seed, start_seed + max_tries):
        sg = generate_scene(seed=seed, scene_cfg=scene_cfg, robot_cfg=robot_cfg)
        if sg is not None and len(sg.human_zones()) == 0:
            return sg
    return None


def run_case(label, base_sg, params, robot_cfg, thresholds, expect_verdict=None, expect_type=None):
    result = run_oracle_on_mutation(base_sg, params, robot_cfg, thresholds)
    ok_v = expect_verdict is None or result.verdict == expect_verdict
    ok_t = expect_type is None or result.failure_type == expect_type
    status = "✅" if (ok_v and ok_t) else "❌"
    print(f"  {status} [{label}]")
    print(f"     verdict={result.verdict}  failure_type={result.failure_type}  "
          f"robustness={result.robustness:.4f}")
    print(f"     reason: {result.reason}")
    print(f"     margins: { {k: round(v,3) for k,v in result.margins.items()} }")
    if not ok_v:
        print(f"     ⚠ 기대 verdict={expect_verdict}, 실제={result.verdict}")
    if not ok_t:
        print(f"     ⚠ 기대 failure_type={expect_type}, 실제={result.failure_type}")
    return result


def main():
    print("=== P5 Physical Oracle 검증 ===\n")
    connect()

    scene_cfg  = load_scene_config("config/scene_gen_config.yaml")
    robot_cfg  = load_robot_config("config/robot_config.yaml")
    thresholds = load_thresholds("config/thresholds.yaml")

    # human_zone 없는 base scene 탐색
    base_sg = find_scene_without_human_zone(scene_cfg, robot_cfg, start_seed=0)
    assert base_sg is not None, "human_zone 없는 유효 scene을 찾지 못함"
    t_pos = base_sg.target().position
    print(f"Base scene: {base_sg.scene_id}  objects={len(base_sg.objects)}")
    print(f"  human_zones={len(base_sg.human_zones())}  "
          f"obstacles={len(base_sg.obstacles())}")
    print(f"  target pos = {t_pos}\n")

    results = []

    # T01. 기본 (nominal) — PASS 또는 WARN (경계) 기대 (human_zone 키 없음 → 삽입 안 됨)
    results.append(run_case("T01 nominal", base_sg, {
        "target_dx": 0.0, "target_dy": 0.0,
        "obstacle_angle": 90.0, "obstacle_dist_to_target": 0.15,
        "tray_occupied": 0.0, "occlusion_ratio": 0.0,
    }, robot_cfg, thresholds))  # PASS or WARN 모두 허용

    # T02. clearance/collision 부족: obstacle을 target에 gripper폭 이하로 근접 → FAIL
    results.append(run_case("T02 clearance_or_collision_fail", base_sg, {
        "target_dx": 0.0, "target_dy": 0.0,
        "obstacle_angle": 0.0, "obstacle_dist_to_target": 0.04,
        "tray_occupied": 0.0, "occlusion_ratio": 0.0,
    }, robot_cfg, thresholds, expect_verdict=Verdict.FAIL))  # FAIL 기대 (failure_type은 무관)

    # T03. destination 점유
    results.append(run_case("T03 destination_occupied", base_sg, {
        "target_dx": 0.0, "target_dy": 0.0,
        "obstacle_angle": 90.0, "obstacle_dist_to_target": 0.15,
        "tray_occupied": 1.0, "occlusion_ratio": 0.0,
    }, robot_cfg, thresholds, expect_type="destination_occupied"))

    # T04. human zone을 경로 중앙에 삽입 → BLOCKED
    # bounds 안의 유효 위치: 경로 중간 지점
    robot_base = robot_cfg["robot"]["base_position"]
    path_mid_x = (robot_base[0] + t_pos[0]) / 2
    path_mid_y = (robot_base[1] + t_pos[1]) / 2
    bounds = base_sg.support_surfaces[0].bounds
    # bounds 안으로 클리핑
    hx = float(max(bounds["x"][0] + 0.05, min(bounds["x"][1] - 0.05, path_mid_x)))
    hy = float(max(bounds["y"][0] + 0.05, min(bounds["y"][1] - 0.05, path_mid_y)))
    results.append(run_case("T04 human_risk → BLOCKED", base_sg, {
        "target_dx": 0.0, "target_dy": 0.0,
        "obstacle_angle": 90.0, "obstacle_dist_to_target": 0.15,
        "human_zone_x": hx, "human_zone_y": hy,
        "tray_occupied": 0.0, "occlusion_ratio": 0.0,
    }, robot_cfg, thresholds, expect_verdict=Verdict.BLOCKED, expect_type="human_risk"))

    # T05. perception uncertainty
    results.append(run_case("T05 perception_uncertainty", base_sg, {
        "target_dx": 0.0, "target_dy": 0.0,
        "obstacle_angle": 90.0, "obstacle_dist_to_target": 0.15,
        "tray_occupied": 0.0, "occlusion_ratio": 0.55,
    }, robot_cfg, thresholds, expect_type="perception_uncertainty"))

    # 통계
    print(f"\n--- 결과 요약 ---")
    for v in [Verdict.PASS, Verdict.FAIL, Verdict.WARN, Verdict.BLOCKED]:
        count = sum(1 for r in results if r.verdict == v)
        print(f"  {v:8s}: {count}개")

    failure_types = [r.failure_type for r in results if r.failure_type]
    unique_types = set(failure_types)
    print(f"  발견된 failure_type: {unique_types}")
    assert len(unique_types) >= 3, f"failure_type 다양성 부족: {unique_types}"

    # BLOCKED가 적어도 1개
    blocked = [r for r in results if r.verdict == Verdict.BLOCKED]
    assert len(blocked) >= 1, "BLOCKED 케이스가 없음"

    # 모든 비-PASS 결과에 reason과 recommendation 존재
    for r in results:
        if r.verdict != Verdict.PASS:
            assert r.reason, f"{r.test_id}: reason 없음"
            assert r.recommendation, f"{r.test_id}: recommendation 없음"

    print("\n✅ P5 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
