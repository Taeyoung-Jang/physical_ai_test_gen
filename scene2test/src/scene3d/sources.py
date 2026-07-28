"""sources.py — 입력 3D scene 데이터의 형식을 판별하고 적절한 백엔드로 위임한다.

이 모듈이 "Scene Graph 생성" 단계(Stage 1)의 진입점이다. CLI/코드는 이 모듈의
`resolve_source()` + `generate_scene_graph()` 두 함수만 알면 되고, 입력이 HM3D
데이터셋인지 임의의 mesh 파일인지 이미 만들어진 SceneGraph JSON인지는 신경 쓸
필요가 없다 — 여기서 판별해서 알맞은 백엔드로 위임한다.

지원 형식:
  - HM3D scene id (예: "00800")            → hm3d_dataset + hm3d_semantics 백엔드
  - 임의의 mesh 파일 (.glb/.gltf/.obj/.ply) → 최소 SceneGraph (인스턴스 분해 불가.
    지지면은 `support_surface` 인자로 직접 지정하지 않으면 비어 있다)
  - 이미 만들어진 SceneGraph JSON            → 그대로 로드 (Stage 1 스킵)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from scene_graph import ObjectNode, Role, SceneGraph, SupportSurface

_MESH_EXTENSIONS = (".glb", ".gltf", ".obj", ".ply")


@dataclass
class SceneSource:
    """`resolve_source()`가 반환하는, 실제 사용 가능한 파일 경로 묶음."""

    kind: str  # "hm3d" | "mesh_file" | "scene_graph_json"
    scene_id: str
    glb_path: str
    semantic_glb_path: Optional[str] = None
    semantic_txt_path: Optional[str] = None
    scene_graph_json_path: Optional[str] = None


def detect_source_kind(ref: str) -> str:
    """ref(경로 또는 HM3D scene id 문자열)를 보고 입력 형식을 판별한다.

    - `.json` 확장자                         → 이미 만들어진 SceneGraph
    - 실존하는 mesh 파일 경로(.glb/.gltf/.obj/.ply) → 임의 mesh
    - 그 외 (파일로 존재하지 않는 짧은 문자열)  → HM3D scene id로 간주
    """
    lower = ref.lower()
    if lower.endswith(".json"):
        return "scene_graph_json"
    if os.path.isfile(ref) and lower.endswith(_MESH_EXTENSIONS):
        return "mesh_file"
    return "hm3d"


def resolve_source(ref: str, split: str = "minival") -> SceneSource:
    """ref를 실제 사용 가능한 `SceneSource`로 해석한다.

    kind == "hm3d"일 때만 hm3d_dataset을 lazy import한다 — 임의 mesh나
    이미 만들어진 SceneGraph JSON을 다룰 때는 HM3D 데이터셋이 로컬에 없어도
    이 함수가 정상 동작해야 하기 때문이다.
    """
    kind = detect_source_kind(ref)

    if kind == "scene_graph_json":
        sg_peek = SceneGraph.load(ref)
        mesh_ref = sg_peek.meta.get("source_mesh_path")
        if not mesh_ref:
            raise ValueError(
                f"{ref!r}는 SceneGraph JSON이지만 meta.source_mesh_path가 없어 "
                "mesh geometry 경로를 찾을 수 없습니다."
            )
        return SceneSource(
            kind="scene_graph_json",
            scene_id=sg_peek.scene_id,
            glb_path=mesh_ref,
            scene_graph_json_path=ref,
        )

    if kind == "mesh_file":
        scene_id = os.path.splitext(os.path.basename(ref))[0]
        return SceneSource(kind="mesh_file", scene_id=scene_id, glb_path=ref)

    # kind == "hm3d"
    from .hm3d_dataset import HM3DDataset

    ds = HM3DDataset(split=split)
    extracted = ds.extract(ref)
    return SceneSource(
        kind="hm3d",
        scene_id=extracted.entry.scene_dir,
        glb_path=extracted.glb_path,
        semantic_glb_path=extracted.semantic_glb_path,
        semantic_txt_path=extracted.semantic_txt_path,
    )


def generate_scene_graph(
    source: SceneSource,
    offset: Optional[list[float]] = None,
    include_structural: bool = True,
    support_surface: Optional[dict] = None,
) -> SceneGraph:
    """Stage 1 진입점: `SceneSource` → `SceneGraph`. source.kind에 따라 위임한다.

    Args:
        offset: mesh_loader.convert_glb_to_obj()가 계산한 좌표 오프셋. hm3d
            백엔드가 인스턴스 bbox를 mesh_loader와 동일한 좌표계로 정렬하는 데
            필요하다 (mesh_file/scene_graph_json 백엔드는 사용하지 않는다).
        include_structural: hm3d 백엔드 전용. 로봇 시뮬레이션에 쓸 SceneGraph는
            벽/기둥 같은 구조물도 장애물 후보로 포함해야 하므로 기본 True.
        support_surface: mesh_file 백엔드 전용. 임의 mesh에서는 지지면을 자동
            추론할 수 없으므로 `{"bounds": {"x":[..],"y":[..]}, "height": z}`
            형태로 직접 지정해야 한다. 생략하면 지지면 없는 SceneGraph를 반환
            한다 (호출자가 알고 있는 경우에만 채워 넣을 수 있는 정직한 한계).

    Raises:
        ValueError: hm3d 소스인데 semantic annotation 파일이 없는 경우.
    """
    if source.kind == "scene_graph_json":
        return SceneGraph.load(source.scene_graph_json_path)

    if source.kind == "hm3d":
        if source.semantic_glb_path is None or source.semantic_txt_path is None:
            raise ValueError(
                f"HM3D 씬 {source.scene_id!r}에는 semantic annotation이 없어 "
                "SceneGraph를 자동 생성할 수 없습니다."
            )
        from .hm3d_semantics import build_scene_graph, extract_instances

        instances = extract_instances(
            source.semantic_glb_path, source.semantic_txt_path, offset=offset
        )
        return build_scene_graph(
            instances, scene_id=source.scene_id,
            include_structural=include_structural,
        )

    if source.kind == "mesh_file":
        return _build_minimal_scene_graph(source, support_surface)

    raise ValueError(f"알 수 없는 source kind: {source.kind!r}")


def _build_minimal_scene_graph(
    source: SceneSource, support_surface: Optional[dict]
) -> SceneGraph:
    """semantic annotation 없는 임의 mesh용 최소 SceneGraph.

    인스턴스 단위 분해가 불가능하므로 전체 mesh AABB를 단일 OBSTACLE
    ObjectNode로 담는다. 이 정도로도 mesh_loader/workspace_setup가 HM3D가
    아닌 입력에도 그대로 동작한다는 것을 증명하기엔 충분하다 — 풍부한
    인스턴스 분해는 별도 인식 파이프라인(perception.py) 또는 이미 만들어진
    SceneGraph JSON을 붙이는 쪽으로 해결한다.
    """
    import trimesh

    mesh = trimesh.load(source.glb_path, force="mesh")
    lo, hi = mesh.bounds
    node = ObjectNode(
        id=f"{source.scene_id}_geometry",
        role=Role.OBSTACLE,
        position=((lo + hi) / 2).tolist(),
        size=(hi - lo).tolist(),
        movable=False,
        shape="mesh",
        extra={"category": "unlabeled_scene_geometry"},
    )

    support_surfaces: list[SupportSurface] = []
    if support_surface is not None:
        support_surfaces.append(
            SupportSurface(
                id=f"{source.scene_id}_surface",
                type="plane",
                height=support_surface["height"],
                bounds=support_surface["bounds"],
            )
        )

    return SceneGraph(
        scene_id=source.scene_id,
        support_surfaces=support_surfaces,
        objects=[node],
        meta={"source": "mesh_file", "source_mesh_path": source.glb_path},
    )
