"""test_p18 — scene3d.sources 입력 판별/디스패치 검증.

HM3D 데이터셋 없이도 전부 실행 가능한 순수 로직 테스트: detect_source_kind의
3분기, mesh_file 경로의 최소 SceneGraph 생성(trimesh로 만든 합성 box GLB),
scene_graph_json 경로의 왕복 로드.

실행:
  uv run --extra scene3d python tests/test_p18_sources.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np


def test_detect_source_kind():
    from scene3d.sources import detect_source_kind

    assert detect_source_kind("data/scene3d_scene_graphs/00800.json") == "scene_graph_json"
    assert detect_source_kind("00800") == "hm3d"
    assert detect_source_kind("some_scene_id_not_a_file") == "hm3d"

    with tempfile.TemporaryDirectory() as tmp:
        mesh_path = os.path.join(tmp, "room.glb")
        open(mesh_path, "w").close()  # 내용은 무관 — 확장자+존재 여부만 판별에 씀
        assert detect_source_kind(mesh_path) == "mesh_file"

    print("[1] detect_source_kind 3분기 OK")


def test_mesh_file_end_to_end():
    """임의 mesh 파일 → resolve_source → generate_scene_graph 전체 경로.

    HM3D와 무관한 합성 mesh(trimesh box)로, robot_workspace/mesh_loader가
    실제로 HM3D 없이도 동작한다는 것을 증명한다.
    """
    import trimesh

    from scene3d.sources import generate_scene_graph, resolve_source

    with tempfile.TemporaryDirectory() as tmp:
        mesh_path = os.path.join(tmp, "table_room.glb")
        box = trimesh.creation.box(extents=[2.0, 1.5, 0.8])
        box.apply_translation([1.0, 0.75, 0.4])  # 바닥에 닿게 이동
        box.export(mesh_path)

        source = resolve_source(mesh_path)
        assert source.kind == "mesh_file"
        assert source.scene_id == "table_room"
        assert source.semantic_glb_path is None

        # support_surface 없이 호출 — 지지면 없는 최소 SceneGraph
        sg_bare = generate_scene_graph(source)
        assert len(sg_bare.objects) == 1
        assert sg_bare.objects[0].extra["category"] == "unlabeled_scene_geometry"
        assert sg_bare.support_surfaces == []
        obj_size = np.array(sg_bare.objects[0].size)
        assert np.allclose(obj_size, [2.0, 1.5, 0.8], atol=0.05), \
            f"mesh AABB 크기 불일치: {obj_size}"

        # support_surface를 직접 지정하면 지지면 포함
        sg_with_surface = generate_scene_graph(
            source,
            support_surface={
                "bounds": {"x": [0.0, 2.0], "y": [0.0, 1.5]},
                "height": 0.8,
            },
        )
        assert len(sg_with_surface.support_surfaces) == 1
        assert sg_with_surface.support_surfaces[0].height == 0.8

    print("[2] mesh_file 경로 OK: 최소 SceneGraph + support_surface 지정 모두 동작")


def test_scene_graph_json_roundtrip():
    """scene_graph_json 경로: meta.source_mesh_path로 mesh geometry를 되찾는다."""
    from scene3d.sources import generate_scene_graph, resolve_source
    from scene_graph import ObjectNode, Role, SceneGraph

    with tempfile.TemporaryDirectory() as tmp:
        mesh_path = os.path.join(tmp, "fake.glb")
        open(mesh_path, "w").close()
        sg_path = os.path.join(tmp, "prebuilt.json")

        sg = SceneGraph(
            scene_id="prebuilt_scene",
            objects=[ObjectNode(
                id="obj_1", role=Role.OBSTACLE,
                position=[0.0, 0.0, 0.0], size=[0.1, 0.1, 0.1],
            )],
            meta={"source_mesh_path": mesh_path},
        )
        sg.save(sg_path)

        source = resolve_source(sg_path)
        assert source.kind == "scene_graph_json"
        assert source.scene_id == "prebuilt_scene"
        assert source.glb_path == mesh_path

        restored = generate_scene_graph(source)
        assert restored.scene_id == "prebuilt_scene"
        assert len(restored.objects) == 1

    print("[3] scene_graph_json 경로 OK: meta.source_mesh_path 왕복")


def main():
    test_detect_source_kind()
    test_mesh_file_end_to_end()
    test_scene_graph_json_roundtrip()
    print("\ntest_p18 PASS")


if __name__ == "__main__":
    main()
