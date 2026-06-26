"""case_apply.py — 새 객체(generated asset) 삽입 메커니즘.

기존 scene_builder.apply_mutation 은 기존 객체 이동만 가능하고 새 객체를 삽입하지
못한다. 여기서는 apply_mutation 을 전혀 건드리지 않고, 복사본 SceneGraph 에
generated asset 을 ObjectNode 로 append 한다. 삽입된 노드는 기존 _spawn_object 가
그대로 스폰한다(primitive box/cylinder).
"""
from __future__ import annotations

import copy
from typing import Optional

import scene_builder as sb
from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.types import FailureCaseCandidate
from scene_graph import SceneGraph, UnknownRegion


def insert_assets(sg: SceneGraph, insert_specs: list[dict],
                  asset_bank: GeneratedAssetBank) -> SceneGraph:
    """deepcopy 후 insert_specs 의 asset 들을 ObjectNode 로 append. 원본 sg 불변.

    각 spec: {"asset_id", "position", "obj_id", "extra"?(optional)}.
    """
    out = copy.deepcopy(sg)
    for spec in insert_specs:
        asset = asset_bank.get(spec["asset_id"])
        node = asset.to_object_node(obj_id=spec["obj_id"], position=spec["position"])
        if spec.get("extra"):
            node.extra.update(spec["extra"])
        out.objects.append(node)
    return out


def apply_case(sg: SceneGraph, case: FailureCaseCandidate,
               asset_bank: GeneratedAssetBank,
               mutation_params: Optional[dict] = None) -> SceneGraph:
    """(선택)기존 mutation 적용 → asset 삽입 → occluder면 UnknownRegion 추가.

    mutation_params 는 case.mutation_params 보다 우선한다(boundary refiner 용 override).
    """
    mp = mutation_params if mutation_params is not None else case.mutation_params
    base = sb.apply_mutation(sg, mp) if mp else copy.deepcopy(sg)
    out = insert_assets(base, case.insert_specs, asset_bank)

    # occluder family: target 중심 UnknownRegion (기존 표현 재사용)
    occ = case.occlusion_ratio
    if occ and occ > 0.0 and out.target() is not None:
        out.unknown_regions.append(UnknownRegion(
            id=f"occ_{case.case_id}",
            center=list(out.target().position),
            radius=0.10,
            occlusion_ratio=occ,
        ))
    return out
