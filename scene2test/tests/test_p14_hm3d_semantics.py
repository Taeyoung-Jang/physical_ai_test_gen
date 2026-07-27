"""test_p14 — HM3D semantic → 실측 SceneGraph 검증 (Phase 2).

HM3D 데이터셋(tar)이 없는 환경에서는 전체를 skip한다.

실행:
  uv run --extra hm3d python tests/test_p14_hm3d_semantics.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np


def main():
    from hm3d.dataset import DEFAULT_DATASET_DIR, HM3DDataset
    from hm3d.loader import convert_glb_to_obj, scene_extent_pybullet
    from hm3d.semantics import (
        build_scene_graph,
        extract_instances,
        parse_semantic_txt,
        select_support_surfaces,
    )

    if not os.path.isdir(DEFAULT_DATASET_DIR):
        print(f"SKIP: HM3D 데이터셋 없음 ({DEFAULT_DATASET_DIR})")
        return

    ds = HM3DDataset(split="minival")

    # 1. 인덱스: minival 10개 씬, semantic 4개
    scenes = ds.list_scenes()
    assert len(scenes) == 10, f"minival 씬 수: {len(scenes)}"
    semantic_scenes = [e for e in scenes if e.has_semantic]
    assert len(semantic_scenes) == 4, f"semantic 씬 수: {len(semantic_scenes)}"
    print(f"[1] 인덱스 OK: 10개 씬, semantic {len(semantic_scenes)}개")

    # 2. 팔레트 파싱
    extracted = ds.extract("00800")
    palette = parse_semantic_txt(extracted.semantic_txt_path)
    assert len(palette) > 600, f"팔레트 크기: {len(palette)}"
    cats = {inst.category for inst in palette.values()}
    assert "wall" in cats and "bed" in cats
    print(f"[2] 팔레트 OK: {len(palette)}개 인스턴스, {len(cats)}개 카테고리")

    # 3. 인스턴스 추출 — bbox가 씬 bounds 안에 있어야 함
    converted = convert_glb_to_obj(extracted.glb_path, extracted.entry.scene_dir)
    instances = extract_instances(
        extracted.semantic_glb_path,
        extracted.semantic_txt_path,
        offset=converted.offset,
    )
    assert len(instances) > 400, f"추출 인스턴스: {len(instances)}"
    lo, hi = scene_extent_pybullet(converted)
    margin = 0.5  # semantic/visual mesh 미세 차이 허용
    for inst in instances:
        assert np.all(inst.bbox_min >= lo - margin), f"#{inst.instance_id} bbox 범위 밖"
        assert np.all(inst.bbox_max <= hi + margin), f"#{inst.instance_id} bbox 범위 밖"
        assert np.all(inst.size > 0)
    print(f"[3] 인스턴스 추출 OK: {len(instances)}개, bbox 모두 씬 범위 내")

    # 4. 지지면: 카테고리/높이/면적 조건
    supports = select_support_surfaces(instances)
    assert len(supports) >= 1, "지지면 후보 없음"
    for s in supports:
        assert 0.35 <= s.top_z <= 1.10
        assert s.footprint_area >= 0.08
    print(f"[4] 지지면 OK: {len(supports)}개 (최대 {supports[0].category}, "
          f"{supports[0].footprint_area:.2f}m²)")

    # 5. SceneGraph: Track A 스키마 round-trip
    sg = build_scene_graph(instances, scene_id="hm3d_test")
    assert len(sg.objects) > 200
    assert len(sg.support_surfaces) == len(supports)
    assert all(not o.movable for o in sg.objects)
    # 구조물(벽 등)은 objects에서 제외되어야 함
    obj_cats = {o.extra["category"] for o in sg.objects}
    assert "wall" not in obj_cats and "ceiling" not in obj_cats

    from scene_graph import SceneGraph
    sg2 = SceneGraph.from_json(sg.to_json())
    assert len(sg2.objects) == len(sg.objects)
    assert sg2.meta["source"] == "hm3d_semantic"
    print(f"[5] SceneGraph OK: 객체 {len(sg.objects)}개, 지지면 {len(sg.support_surfaces)}개, "
          "JSON round-trip 통과")

    print("\ntest_p14 PASS")


if __name__ == "__main__":
    main()
