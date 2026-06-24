"""scene_library.py — Scene 라이브러리 기반 Cross-scene 전이 Surrogate.

여러 base scene에서 누적된 데이터로 surrogate를 학습하고,
새 scene에 warm-start로 전이한다.

학습 데이터 한 행:
  x = [scene_features(8) | mutation_params_normalized(8)]  → (16,)
  y = [reach, clearance, collision, safety, goal, perception] → (6,)

warm-start:
  1. 라이브러리 전체 데이터로 surrogate 학습 (cross-scene)
  2. 새 scene 투입 시 warm-start surrogate로 AFS 시작
  3. 새 scene 데이터를 추가로 fine-tune (실시간 갱신)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np

from scene_graph import SceneGraph
from surrogate_model import MultiOutputSurrogate, RFSurrogate, build_training_data, MARGIN_NAMES


# ---------------------------------------------------------------------------
# 라이브러리 데이터 관리
# ---------------------------------------------------------------------------

class SceneLibrary:
    """여러 scene에서 수집된 테스트 결과를 통합 관리한다."""

    def __init__(self, library_dir: str = "data/scene_library"):
        self.library_dir = Path(library_dir)
        self._scene_graphs: dict[str, SceneGraph] = {}
        self._records_by_scene: dict[str, list[dict]] = {}

    # -- scene graph 로드 --
    def load_scene_graphs(self) -> list[SceneGraph]:
        scenes = []
        for f in sorted(self.library_dir.glob("*.json")):
            try:
                sg = SceneGraph.load(str(f))
                self._scene_graphs[sg.scene_id] = sg
                scenes.append(sg)
            except Exception as e:
                print(f"  [warning] {f.name} 로드 실패: {e}")
        return scenes

    # -- 탐색 로그 수집 --
    def load_search_logs(self, log_dir: str = "data/search_logs") -> None:
        """기존 search log JSON 파일들에서 TestRecord를 수집한다."""
        log_path = Path(log_dir)
        if not log_path.exists():
            return
        for f in log_path.glob("*.json"):
            try:
                with open(f, encoding="utf-8") as fp:
                    log = json.load(fp)
                scene_id = log.get("scene_id", "unknown")
                records = log.get("records", [])
                if scene_id not in self._records_by_scene:
                    self._records_by_scene[scene_id] = []
                self._records_by_scene[scene_id].extend(records)
            except Exception as e:
                print(f"  [warning] {f.name} 로드 실패: {e}")

    def add_records(self, scene_id: str, records: list[dict]) -> None:
        if scene_id not in self._records_by_scene:
            self._records_by_scene[scene_id] = []
        self._records_by_scene[scene_id].extend(records)

    def total_records(self) -> int:
        return sum(len(v) for v in self._records_by_scene.values())

    def all_records(self) -> list[dict]:
        result = []
        for recs in self._records_by_scene.values():
            result.extend(recs)
        return result


# ---------------------------------------------------------------------------
# Cross-scene Surrogate 학습
# ---------------------------------------------------------------------------

def train_cross_scene_surrogate(
    library: SceneLibrary,
    surrogate_type: str = "rf",
    random_state: int = 42,
    min_records: int = 20,
) -> Optional[MultiOutputSurrogate]:
    """라이브러리 전체 데이터로 cross-scene surrogate를 학습한다.

    학습 데이터가 min_records 미만이면 None을 반환한다.
    """
    all_recs = library.all_records()
    if len(all_recs) < min_records:
        print(f"  [warn] 학습 데이터 부족: {len(all_recs)} < {min_records}")
        return None

    # feature_vector와 margins가 모두 있는 record만 사용
    valid = [
        r for r in all_recs
        if "feature_vector" in r and "margins" in r
    ]
    if len(valid) < min_records:
        return None

    X, Y = build_training_data(valid)

    if surrogate_type == "gp":
        from surrogate_model import GPSurrogate
        surrogate = GPSurrogate(random_state=random_state)
    else:
        surrogate = RFSurrogate(random_state=random_state)

    surrogate.fit(X, Y)
    print(f"  Cross-scene surrogate 학습 완료: "
          f"{len(valid)}개 records  "
          f"n_scenes={len(library._records_by_scene)}")
    return surrogate


# ---------------------------------------------------------------------------
# 전이 학습 실험
# ---------------------------------------------------------------------------

def run_transfer_experiment(
    test_scene: SceneGraph,
    robot_cfg: dict,
    thresholds: dict,
    library: SceneLibrary,
    n_rounds: int = 5,
    tests_per_round: int = 10,
    seed: int = 42,
    log_dir: str = "data/search_logs",
) -> dict[str, dict]:
    """세 가지 방법을 같은 새 scene에서 비교한다.

      random    : 무작위 선택
      cold      : 해당 scene만으로 학습 (cold-start)
      warm      : 라이브러리 surrogate warm-start

    Returns: {method_name: summary_dict}
    """
    import sys
    sys.path.insert(0, os.path.dirname(__file__))

    from active_failure_search import ActiveFailureSearch, SearchConfig, run_comparison
    from dataclasses import asdict

    base_cfg = SearchConfig(
        num_rounds=n_rounds,
        tests_per_round=tests_per_round,
        candidate_pool_size=500,
        min_train_size=12,
        surrogate_type="rf",
        seed=seed,
        log_dir=log_dir,
    )

    # warm-start surrogate 학습
    warm_surrogate = train_cross_scene_surrogate(library, random_state=seed)

    results = run_comparison(
        test_scene, robot_cfg, thresholds, base_cfg,
        pretrained_surrogate=warm_surrogate,
    )
    return results


# ---------------------------------------------------------------------------
# 라이브러리 구축: AFS를 여러 scene에 실행해 데이터 수집
# ---------------------------------------------------------------------------

def build_library_from_scenes(
    scene_graphs: list[SceneGraph],
    robot_cfg: dict,
    thresholds: dict,
    rounds_per_scene: int = 3,
    tests_per_round: int = 8,
    seed: int = 0,
    log_dir: str = "data/search_logs",
) -> SceneLibrary:
    """여러 scene에서 AFS를 실행하고 SceneLibrary를 구성한다."""
    from active_failure_search import ActiveFailureSearch, SearchConfig

    library = SceneLibrary()
    for i, sg in enumerate(scene_graphs):
        print(f"\n[{i+1}/{len(scene_graphs)}] {sg.scene_id} 탐색 중...")
        cfg = SearchConfig(
            num_rounds=rounds_per_scene,
            tests_per_round=tests_per_round,
            candidate_pool_size=300,
            min_train_size=10,
            mode="cold",
            seed=seed + i * 100,
            log_dir=log_dir,
        )
        searcher = ActiveFailureSearch(sg, robot_cfg, thresholds, cfg)
        records = searcher.run()
        library.add_records(sg.scene_id,
                            [r.to_dict() for r in records])
    return library
