"""asset_bank.py — Generated Asset Bank + 씬 시맨틱 주석.

블루프린트 14.2 "1단계: Procedural Asset Bank" 를 따른다. 실제 3D mesh 생성 대신
primitive(box/cylinder) 기반 procedural asset 카탈로그를 만들고 index.json 으로 영속화한다.
asset 은 기존 scene_builder._spawn_object 가 그대로 스폰할 수 있는 ObjectNode 로 변환된다.

annotate_scene_semantics: 기존 씬 객체에 semantic tag / 색 / target 유사도를 주입한다
(ObjectNode.extra 에만 저장하므로 SceneGraph 스키마는 불변).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from lam_guided.types import GeneratedAsset
from scene_graph import ObjectNode, Role, SceneGraph

# ---------------------------------------------------------------------------
# Procedural 카탈로그 (모두 primitive, mesh 없음)
# ---------------------------------------------------------------------------

_CATALOG: list[GeneratedAsset] = [
    # semantic distractor — target(빨강 can/block)과 유사
    GeneratedAsset("distractor_red_can", Role.DISTRACTOR, "cylinder",
                   [0.066, 0.066, 0.10], ["red", "can", "cylinder"], 0.92,
                   ["semantic_distractor"]),
    GeneratedAsset("distractor_red_block", Role.DISTRACTOR, "block",
                   [0.06, 0.06, 0.08], ["red", "block", "box"], 0.78,
                   ["semantic_distractor"]),
    GeneratedAsset("distractor_blue_can", Role.DISTRACTOR, "cylinder",
                   [0.066, 0.066, 0.10], ["blue", "can", "cylinder"], 0.45,
                   ["semantic_distractor"]),
    # occluder — target을 가리는 키 큰 물체
    GeneratedAsset("occluder_tall_panel", Role.OBSTACLE, "block",
                   [0.04, 0.12, 0.22], ["tall", "panel"], 0.10, ["occluder"]),
    GeneratedAsset("occluder_cup", Role.OBSTACLE, "cylinder",
                   [0.08, 0.08, 0.14], ["cup", "cylinder"], 0.20, ["occluder"]),
    # path blocker / clutter
    GeneratedAsset("blocker_box", Role.OBSTACLE, "block",
                   [0.09, 0.09, 0.10], ["box", "clutter"], 0.15, ["path_blocker"]),
    GeneratedAsset("blocker_bar", Role.OBSTACLE, "block",
                   [0.03, 0.18, 0.08], ["bar", "clutter"], 0.10, ["path_blocker"]),
    # human safety
    GeneratedAsset("human_proxy", Role.HUMAN_ZONE, "cylinder",
                   [0.30, 0.30, 1.80], ["human", "person"], 0.0,
                   ["human_safety_intrusion"], mass=0.0, extra={"radius": 0.15}),
]


class GeneratedAssetBank:
    """procedural asset 카탈로그. index.json 으로 저장/로드하고 query/get 을 제공한다."""

    def __init__(self, assets: Optional[list[GeneratedAsset]] = None):
        self._assets: dict[str, GeneratedAsset] = {}
        for a in (assets if assets is not None else _CATALOG):
            self._assets[a.asset_id] = a

    # -- 영속화 --
    def save_index(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"assets": [a.to_dict() for a in self._assets.values()]},
                      f, indent=2, ensure_ascii=False)

    @classmethod
    def load_index(cls, path: str) -> "GeneratedAssetBank":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls([GeneratedAsset.from_dict(a) for a in d.get("assets", [])])

    @classmethod
    def default(cls, index_path: Optional[str] = None) -> "GeneratedAssetBank":
        """index.json 이 있으면 로드, 없으면 기본 카탈로그를 만들고 저장한다."""
        if index_path and os.path.exists(index_path):
            return cls.load_index(index_path)
        bank = cls()
        if index_path:
            bank.save_index(index_path)
        return bank

    # -- 조회 --
    def get(self, asset_id: str) -> GeneratedAsset:
        return self._assets[asset_id]

    def all(self) -> list[GeneratedAsset]:
        return list(self._assets.values())

    def query(self, role: Optional[str] = None, family: Optional[str] = None,
              min_similarity: float = 0.0) -> list[GeneratedAsset]:
        out = []
        for a in self._assets.values():
            if role is not None and a.role != role:
                continue
            if family is not None and family not in a.family_affinity:
                continue
            if a.visual_similarity_to_target < min_similarity:
                continue
            out.append(a)
        return out


# ---------------------------------------------------------------------------
# 씬 시맨틱 주석
# ---------------------------------------------------------------------------

# role → 기본 색/태그 (scene_builder._ROLE_COLORS 의도와 일치)
_ROLE_COLOR_NAME = {
    Role.TARGET: "red",
    Role.OBSTACLE: "blue",
    Role.DESTINATION: "green",
    Role.DISTRACTOR: "grey",
    Role.HUMAN_ZONE: "orange",
}


def _shape_tags(obj: ObjectNode) -> list[str]:
    tags = [obj.shape]
    if obj.shape in ("can", "cylinder"):
        tags += ["can", "cylinder"]
    if obj.shape in ("block", "box"):
        tags += ["block", "box"]
    if obj.shape in ("tray", "bin"):
        tags += ["tray", "container"]
    return tags


def _color_match(a: str, b: str) -> float:
    return 1.0 if a == b else 0.0


def _shape_match(a: ObjectNode, b: ObjectNode) -> float:
    sa, sb = set(_shape_tags(a)), set(_shape_tags(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def annotate_scene_semantics(sg: SceneGraph) -> SceneGraph:
    """복사본을 만들어 각 객체에 semantic_tags / color / visual_similarity_to_target 주입.

    이미 주입된 값(예: 삽입된 generated asset)은 보존한다.
    """
    import copy
    out = copy.deepcopy(sg)
    target = out.target()
    t_color = _ROLE_COLOR_NAME.get(Role.TARGET, "red") if target else "red"

    for obj in out.objects:
        if "color" not in obj.extra:
            obj.extra["color"] = _ROLE_COLOR_NAME.get(obj.role, "grey")
        if "semantic_tags" not in obj.extra:
            obj.extra["semantic_tags"] = [obj.extra["color"]] + _shape_tags(obj)
        if "visual_similarity_to_target" not in obj.extra:
            if target is None or obj.id == target.id:
                obj.extra["visual_similarity_to_target"] = 1.0 if (
                    target and obj.id == target.id) else 0.0
            else:
                sim = (0.6 * _color_match(obj.extra["color"], t_color)
                       + 0.4 * _shape_match(obj, target))
                obj.extra["visual_similarity_to_target"] = round(sim, 3)
    return out
