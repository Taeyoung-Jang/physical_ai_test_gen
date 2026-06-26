"""P13 완료 기준 검증 — 3D object generation + default 폴백.

생성 모델(Shap-E) 없이도 통과한다(폴백·메쉬로딩만 검증; 실제 생성은 느려서 제외).

  1: GeneratedAsset(mesh_path) → to_object_node 가 shape='mesh' 로 변환
  2: _spawn_object 가 메쉬 OBJ + box collision proxy 로 스폰
  3: acquire_asset(no generator) → default procedural asset 폴백
  4: acquire_asset(NullGenerator)  → default 폴백 (명시적 '모델 없음')
  5: ShapEGenerator 인스턴스화는 항상 되고, 미설치 시 available()=False 로 폴백

실행: PYBULLET_MODE=DIRECT uv run python tests/test_p13_asset_gen.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

import pybullet as p
import pybullet_data

import scene_builder
import sim_runner
from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.asset_gen import NullGenerator, acquire_asset, make_generator
from lam_guided.types import GeneratedAsset
from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface
from sim_runner import get_closest_distance, load_robot, load_robot_config

_CUBE_OBJ = """v -0.03 -0.03 0.0
v 0.03 -0.03 0.0
v 0.03 0.03 0.0
v -0.03 0.03 0.0
v -0.03 -0.03 0.1
v 0.03 -0.03 0.1
v 0.03 0.03 0.1
v -0.03 0.03 0.1
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""


def _write_cube(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(_CUBE_OBJ)


def main():
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid
    sim_runner._ROBOT_BODY_ID = None
    robot_cfg = load_robot_config("config/robot_config.yaml")
    bank = GeneratedAssetBank.default("data/generated_assets/index.json")

    print("[1] mesh asset → to_object_node shape=mesh ...", end=" ")
    mesh = "/tmp/genmesh_p13/model.obj"
    _write_cube(mesh)
    asset = GeneratedAsset("gen_test", Role.DISTRACTOR, "mesh", [0.06, 0.06, 0.10],
                           ["red", "can"], 0.85, ["semantic_distractor"],
                           mesh_path=mesh, source="shap_e")
    node = asset.to_object_node("gen_obj", [0.55, 0.1, 0.0])
    assert node.shape == "mesh" and node.extra.get("mesh_path") == mesh
    print("OK")

    print("[2] _spawn_object 메쉬 로딩 + collision proxy ...", end=" ")
    sg = SceneGraph("p13",
        support_surfaces=[SupportSurface("t", "plane", 0.0,
                                         {"x": [0.3, 0.8], "y": [-0.35, 0.35]})],
        objects=[ObjectNode("target_0", Role.TARGET, [0.48, 0.0, 0.05],
                            [0.066, 0.066, 0.10], True, "can"), node])
    scene_builder.reset_simulation()
    bm = scene_builder.load_scene(sg)
    assert "gen_obj" in bm, "메쉬 asset 미스폰"
    robot = load_robot(robot_cfg)
    d = get_closest_distance(robot, bm["gen_obj"])
    assert d < 1.0, "collision proxy 비활성"
    print("OK")

    print("[3] acquire_asset(no generator) → default 폴백 ...", end=" ")
    aid = acquire_asset(bank, "semantic_distractor", spec={"prompt": "x"})
    a = bank.get(aid)
    assert a.source == "procedural" and a.shape in ("cylinder", "block")
    print(f"OK ({aid})")

    print("[4] acquire_asset(NullGenerator) → default 폴백 ...", end=" ")
    aid = acquire_asset(bank, "occluder", spec={"prompt": "x"}, generator=NullGenerator())
    assert bank.get(aid).source == "procedural"
    print(f"OK ({aid})")

    print("[5] ShapEGenerator 인스턴스화 + available() 게이트 ...", end=" ")
    g = make_generator("shap_e")
    # 설치 여부와 무관하게 인스턴스화는 됨. available()이 False면 폴백이 동작해야 함.
    if not g.available():
        aid = acquire_asset(bank, "semantic_distractor", spec={"prompt": "x"}, generator=g)
        assert bank.get(aid).source == "procedural"
    print(f"OK (available={g.available()})")

    p.disconnect(physicsClientId=cid)
    print("\n✅ P13 완료 기준 전부 통과 (3D 메쉬 로딩 + 생성 없으면 default 폴백)")


if __name__ == "__main__":
    main()
