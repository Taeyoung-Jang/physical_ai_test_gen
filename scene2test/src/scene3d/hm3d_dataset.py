"""hm3d_dataset.py — HM3D 데이터셋 백엔드: tar 아카이브 인덱싱 + 씬 추출.

scene3d.sources.resolve_source()가 입력을 HM3D scene id로 판별했을 때만
사용하는 모듈 — 다른 3D scene 소스(임의 mesh 파일 등)는 이 모듈을 거치지
않는다.

데이터셋 디렉터리에는 split별 tar 아카이브가 압축 상태로 놓여 있다:
  hm3d-{split}-glb-v0.2.tar              텍스처 포함 whole-house GLB
  hm3d-{split}-semantic-annots-v0.2.tar  .semantic.glb + .semantic.txt (일부 씬만)
  hm3d-{split}-semantic-configs-v0.2.tar habitat 전용 config (미사용)
  hm3d-{split}-habitat-v0.2.tar          basis GLB + navmesh (habitat 전용, 미사용)

tar 전체를 풀지 않고, 씬 단위로 필요한 멤버만 data/scene3d_raw/에 추출한다.
tar 목록은 최초 1회 인덱싱 후 JSON으로 캐시한다.
"""
from __future__ import annotations

import json
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_DATASET_DIR = os.environ.get(
    "HM3D_DATASET_DIR",
    os.path.expanduser(
        "~/Documents/Workspace/3d_scene_data/habitat-matterport-3dresearch/dataset"
    ),
)
DEFAULT_RAW_DIR = "data/scene3d_raw"
HM3D_VERSION = "v0.2"
SPLITS = ("minival", "val", "train")


@dataclass
class SceneEntry:
    """HM3D 씬 하나의 메타 정보."""

    scene_dir: str  # 예: "00800-TEEsavR23oF"
    scene_id: str  # 예: "00800"
    scene_hash: str  # 예: "TEEsavR23oF"
    split: str
    has_semantic: bool = False

    @property
    def glb_member(self) -> str:
        return f"{self.scene_dir}/{self.scene_hash}.glb"

    @property
    def semantic_glb_member(self) -> str:
        return f"{self.scene_dir}/{self.scene_hash}.semantic.glb"

    @property
    def semantic_txt_member(self) -> str:
        return f"{self.scene_dir}/{self.scene_hash}.semantic.txt"


@dataclass
class ExtractedScene:
    """추출 완료된 씬의 로컬 파일 경로."""

    entry: SceneEntry
    glb_path: Path
    semantic_glb_path: Optional[Path] = None
    semantic_txt_path: Optional[Path] = None


@dataclass
class HM3DDataset:
    """tar 아카이브 기반 HM3D 데이터셋 접근자."""

    dataset_dir: str = DEFAULT_DATASET_DIR
    split: str = "minival"
    raw_dir: str = DEFAULT_RAW_DIR
    _index: list[SceneEntry] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.split not in SPLITS:
            raise ValueError(f"지원하지 않는 split: {self.split} (가능: {SPLITS})")

    # ── tar 경로 ────────────────────────────────────────────────────────

    def _tar_path(self, kind: str) -> Path:
        name = f"hm3d-{self.split}-{kind}-{HM3D_VERSION}.tar"
        path = Path(self.dataset_dir) / name
        if not path.exists():
            raise FileNotFoundError(f"tar 아카이브 없음: {path}")
        return path

    # ── 인덱스 ──────────────────────────────────────────────────────────

    @property
    def _index_path(self) -> Path:
        return Path(self.raw_dir) / f"index_{self.split}.json"

    def list_scenes(self, refresh: bool = False) -> list[SceneEntry]:
        """split 내 씬 목록 (semantic annotation 보유 여부 포함).

        최초 1회 tar 목록을 스캔해 JSON 캐시를 만든다.
        """
        if self._index and not refresh:
            return self._index

        if self._index_path.exists() and not refresh:
            data = json.loads(self._index_path.read_text())
            self._index = [SceneEntry(**e) for e in data]
            return self._index

        glb_dirs = self._scan_scene_dirs(self._tar_path("glb"))
        semantic_dirs = self._scan_scene_dirs(self._tar_path("semantic-annots"))

        entries = []
        for scene_dir in sorted(glb_dirs):
            scene_id, _, scene_hash = scene_dir.partition("-")
            entries.append(
                SceneEntry(
                    scene_dir=scene_dir,
                    scene_id=scene_id,
                    scene_hash=scene_hash,
                    split=self.split,
                    has_semantic=scene_dir in semantic_dirs,
                )
            )

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps([e.__dict__ for e in entries], indent=2)
        )
        self._index = entries
        return entries

    @staticmethod
    def _scan_scene_dirs(tar_path: Path) -> set[str]:
        dirs: set[str] = set()
        with tarfile.open(tar_path) as tf:
            for name in tf.getnames():
                top = name.split("/")[0]
                if top and "-" in top:
                    dirs.add(top)
        return dirs

    def resolve(self, ref: str) -> SceneEntry:
        """씬 참조 문자열(id/해시/디렉터리명 접두)을 SceneEntry로 해석한다."""
        scenes = self.list_scenes()
        matches = [
            e
            for e in scenes
            if ref in (e.scene_dir, e.scene_id, e.scene_hash)
            or e.scene_dir.startswith(ref)
        ]
        if not matches:
            raise KeyError(f"씬을 찾을 수 없음: {ref!r} (split={self.split})")
        if len(matches) > 1:
            names = ", ".join(e.scene_dir for e in matches)
            raise KeyError(f"씬 참조가 모호함: {ref!r} → {names}")
        return matches[0]

    # ── 추출 ────────────────────────────────────────────────────────────

    def extract(self, ref: str, with_semantic: bool = True) -> ExtractedScene:
        """씬의 GLB(+semantic) 파일을 raw_dir로 추출한다. 이미 있으면 재사용."""
        entry = self.resolve(ref)
        out_root = Path(self.raw_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        glb_path = out_root / entry.glb_member
        if not glb_path.exists():
            self._extract_members(self._tar_path("glb"), [entry.glb_member], out_root)

        result = ExtractedScene(entry=entry, glb_path=glb_path)

        if with_semantic and entry.has_semantic:
            sem_glb = out_root / entry.semantic_glb_member
            sem_txt = out_root / entry.semantic_txt_member
            missing = [
                m
                for m, path in [
                    (entry.semantic_glb_member, sem_glb),
                    (entry.semantic_txt_member, sem_txt),
                ]
                if not path.exists()
            ]
            if missing:
                self._extract_members(
                    self._tar_path("semantic-annots"), missing, out_root
                )
            result.semantic_glb_path = sem_glb
            result.semantic_txt_path = sem_txt

        return result

    @staticmethod
    def _extract_members(tar_path: Path, members: list[str], out_root: Path) -> None:
        with tarfile.open(tar_path) as tf:
            for member in members:
                tf.extract(member, path=out_root, filter="data")
