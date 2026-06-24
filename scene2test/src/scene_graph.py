"""SceneGraph: the central data contract of Scene2Test.

Every scene source emits this exact structure, regardless of origin:
  - Track A  : procedural generator (scene_generator.py)         -> SceneGraph
  - Track B  : RGB-D perception (vision/rgbd_to_graph.py)        -> SceneGraph
  - Mutation : a base SceneGraph + mutation params               -> SceneGraph

Because the schema is fixed, every downstream stage (feature extraction,
oracles, search, reporting) is agnostic to where the scene came from.

The JSON shape mirrors blueprint section 8.1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# --- Roles -----------------------------------------------------------------
class Role:
    TARGET = "target"            # object to pick (exactly one per scene)
    OBSTACLE = "obstacle"        # movable clutter
    DESTINATION = "destination"  # place goal (tray/bin/zone)
    HUMAN_ZONE = "human_zone"    # safety-critical region
    DISTRACTOR = "distractor"    # irrelevant object


# --- Nodes -----------------------------------------------------------------
@dataclass
class SupportSurface:
    id: str
    type: str                     # "plane"
    height: float                 # z of the surface top
    bounds: dict[str, list[float]]  # {"x": [min, max], "y": [min, max]}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SupportSurface":
        return cls(id=d["id"], type=d["type"], height=d["height"],
                   bounds=d["bounds"])


@dataclass
class ObjectNode:
    id: str
    role: str                     # one of Role.*
    position: list[float]         # [x, y, z], robot base frame, meters
    size: list[float]             # [sx, sy, sz] full extents (AABB), meters
    movable: bool = True
    shape: str = "block"          # block | cylinder | can | tray | bin | zone
    extra: dict[str, Any] = field(default_factory=dict)  # role-specific fields

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ObjectNode":
        return cls(
            id=d["id"], role=d["role"], position=list(d["position"]),
            size=list(d["size"]), movable=d.get("movable", True),
            shape=d.get("shape", "block"), extra=d.get("extra", {}),
        )


@dataclass
class Relation:
    type: str                     # near | on | blocks_path | reachable | occludes
    source: str
    target: str
    distance_m: Optional[float] = None
    value: Optional[Any] = None

    def to_dict(self) -> dict[str, Any]:
        d = {"type": self.type, "source": self.source, "target": self.target}
        if self.distance_m is not None:
            d["distance_m"] = self.distance_m
        if self.value is not None:
            d["value"] = self.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relation":
        return cls(type=d["type"], source=d["source"], target=d["target"],
                   distance_m=d.get("distance_m"), value=d.get("value"))


@dataclass
class UnknownRegion:
    """Camera-occluded / unobserved volume. Approximated as a vertical column."""
    id: str
    center: list[float]           # [x, y, z]
    radius: float
    occlusion_ratio: float = 0.0  # [0, 1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UnknownRegion":
        return cls(id=d["id"], center=list(d["center"]), radius=d["radius"],
                   occlusion_ratio=d.get("occlusion_ratio", 0.0))


# --- Graph -----------------------------------------------------------------
@dataclass
class SceneGraph:
    scene_id: str
    support_surfaces: list[SupportSurface] = field(default_factory=list)
    objects: list[ObjectNode] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    unknown_regions: list[UnknownRegion] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # source, seed, etc.

    # -- access helpers --
    def get_object(self, obj_id: str) -> Optional[ObjectNode]:
        return next((o for o in self.objects if o.id == obj_id), None)

    def by_role(self, role: str) -> list[ObjectNode]:
        return [o for o in self.objects if o.role == role]

    def target(self) -> Optional[ObjectNode]:
        objs = self.by_role(Role.TARGET)
        return objs[0] if objs else None

    def destination(self) -> Optional[ObjectNode]:
        objs = self.by_role(Role.DESTINATION)
        return objs[0] if objs else None

    def obstacles(self) -> list[ObjectNode]:
        return self.by_role(Role.OBSTACLE)

    def human_zones(self) -> list[ObjectNode]:
        return self.by_role(Role.HUMAN_ZONE)

    # -- serialization --
    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "support_surfaces": [s.to_dict() for s in self.support_surfaces],
            "objects": [o.to_dict() for o in self.objects],
            "relations": [r.to_dict() for r in self.relations],
            "unknown_regions": [u.to_dict() for u in self.unknown_regions],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SceneGraph":
        return cls(
            scene_id=d["scene_id"],
            support_surfaces=[SupportSurface.from_dict(x)
                              for x in d.get("support_surfaces", [])],
            objects=[ObjectNode.from_dict(x) for x in d.get("objects", [])],
            relations=[Relation.from_dict(x) for x in d.get("relations", [])],
            unknown_regions=[UnknownRegion.from_dict(x)
                             for x in d.get("unknown_regions", [])],
            meta=d.get("meta", {}),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, s: str) -> "SceneGraph":
        return cls.from_dict(json.loads(s))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "SceneGraph":
        with open(path, encoding="utf-8") as f:
            return cls.from_json(f.read())


if __name__ == "__main__":
    # Round-trip self-check (the P0 completion criterion).
    sg = SceneGraph(
        scene_id="desk_scene_001",
        support_surfaces=[SupportSurface(
            "table_1", "plane", 0.0, {"x": [0.20, 0.80], "y": [-0.35, 0.35]})],
        objects=[
            ObjectNode("red_block", Role.TARGET, [0.45, -0.10, 0.05],
                       [0.06, 0.06, 0.08], True, "block"),
            ObjectNode("blue_obstacle", Role.OBSTACLE, [0.35, -0.08, 0.05],
                       [0.08, 0.08, 0.08], True, "block"),
            ObjectNode("tray", Role.DESTINATION, [0.60, 0.20, 0.03],
                       [0.18, 0.12, 0.04], False, "tray"),
        ],
        relations=[
            Relation("near", "blue_obstacle", "red_block", distance_m=0.11),
            Relation("reachable", "panda_arm", "red_block", value=True),
        ],
        meta={"source": "ground_truth"},
    )
    restored = SceneGraph.from_json(sg.to_json())
    assert restored.to_dict() == sg.to_dict(), "round-trip mismatch"
    assert restored.target().id == "red_block"
    assert len(restored.obstacles()) == 1
    print("SceneGraph round-trip OK:", restored.scene_id)
