"""active_failure_search.py — Active Failure Search Engine.

메인 탐색 루프:
  라운드마다 1,000개 후보 샘플 → surrogate로 score → top-K 선택 → PyBullet 실행 → 모델 갱신

운용 모드:
  "cold"      : 해당 scene만으로 학습 (단일 scene BO)
  "warm"      : 라이브러리 surrogate를 warm-start로 초기화
  "random"    : 무작위 선택 (비교 기준선)

결과는 data/search_logs/ 에 JSON으로 기록된다.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from acquisition import (
    compute_acquisition_scores,
    select_topk_diverse,
)
from feature_extractor import build_feature_batch, build_feature_vector
from mutation_space import (
    sample_initial_seeds,
    sample_random,
)
from physical_oracle import (
    OracleResult,
    Verdict,
    load_thresholds,
    run_oracle_on_mutation,
)
from scene_graph import SceneGraph
from surrogate_model import (
    MARGIN_NAMES,
    GPSurrogate,
    MultiOutputSurrogate,
    RFSurrogate,
)

# ---------------------------------------------------------------------------
# 탐색 설정
# ---------------------------------------------------------------------------

@dataclass
class SearchConfig:
    num_rounds: int = 5           # 탐색 라운드 수
    tests_per_round: int = 10     # 라운드당 실행 테스트 수
    candidate_pool_size: int = 1000
    min_train_size: int = 15      # surrogate 학습 최소 데이터 수
    surrogate_type: str = "rf"    # "rf" | "gp"
    mode: str = "cold"            # "cold" | "warm" | "random"
    seed: int = 42
    log_dir: str = "data/search_logs"
    diversity_lambda: float = 0.30


# ---------------------------------------------------------------------------
# 탐색 기록 단위
# ---------------------------------------------------------------------------

@dataclass
class TestRecord:
    """단일 테스트 실행 결과 + 피처 벡터."""
    test_id: str
    round_idx: int
    scene_id: str
    mutation_params: dict
    feature_vector: list[float]
    margins: dict[str, float]
    robustness: float
    verdict: str
    failure_type: str
    reason: str
    recommendation: str
    acquisition_score: float = 0.0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 메인 탐색 클래스
# ---------------------------------------------------------------------------

class ActiveFailureSearch:

    def __init__(
        self,
        scene_graph: SceneGraph,
        robot_cfg: dict,
        thresholds: dict,
        config: SearchConfig,
        pretrained_surrogate: Optional[MultiOutputSurrogate] = None,
    ):
        self.sg = scene_graph
        self.robot_cfg = robot_cfg
        self.thresholds = thresholds
        self.cfg = config

        self.dataset: list[TestRecord] = []
        self.discovered_failure_types: set[str] = set()
        self._run_id = str(uuid.uuid4())[:8]

        robot_base = robot_cfg["robot"]["base_position"]
        self._robot_base = robot_base
        self._max_reach = robot_cfg["robot"]["max_reach"]

        # Surrogate 초기화
        if config.mode == "warm" and pretrained_surrogate is not None:
            self._surrogate = pretrained_surrogate
        else:
            self._surrogate = self._make_surrogate()

        Path(config.log_dir).mkdir(parents=True, exist_ok=True)

    def _make_surrogate(self) -> MultiOutputSurrogate:
        if self.cfg.surrogate_type == "gp":
            return GPSurrogate(random_state=self.cfg.seed)
        return RFSurrogate(random_state=self.cfg.seed)

    # ------------------------------------------------------------------
    # 단일 테스트 평가 (서브클래스 오버라이드 지점 — 예: hm3d.failure_search)
    # ------------------------------------------------------------------

    def _evaluate(self, params: dict, test_id: str) -> OracleResult:
        return run_oracle_on_mutation(
            self.sg, params, self.robot_cfg, self.thresholds, test_id=test_id
        )

    # ------------------------------------------------------------------
    # 피처 벡터 빌드
    # ------------------------------------------------------------------

    def _build_X(self, mutation_list: list[dict]) -> np.ndarray:
        return build_feature_batch(
            self.sg, mutation_list, self._robot_base, self._max_reach
        )

    def _dataset_X(self) -> Optional[np.ndarray]:
        if not self.dataset:
            return None
        return np.array([rec.feature_vector for rec in self.dataset])

    def _dataset_Y(self) -> Optional[np.ndarray]:
        if not self.dataset:
            return None
        return np.array([
            [rec.margins[m] for m in MARGIN_NAMES]
            for rec in self.dataset
        ])

    # ------------------------------------------------------------------
    # 라운드별 실행
    # ------------------------------------------------------------------

    def _run_round(self, round_idx: int) -> list[TestRecord]:
        rng_seed = self.cfg.seed + round_idx * 1000

        # 1. 후보 샘플링
        if round_idx == 0:
            pool = sample_initial_seeds(
                self.sg, self.robot_cfg,
                k=self.cfg.candidate_pool_size,
                seed=rng_seed,
            )
        else:
            pool = sample_random(
                self.sg, self.robot_cfg,
                n=self.cfg.candidate_pool_size,
                seed=rng_seed,
            )

        if not pool:
            print(f"  라운드 {round_idx}: 유효 후보 없음")
            return []

        X_pool = self._build_X(pool)

        # 2. 테스트 선택
        if self.cfg.mode == "random":
            rng = np.random.default_rng(rng_seed)
            indices = list(rng.choice(len(pool), size=min(self.cfg.tests_per_round, len(pool)),
                                      replace=False))
            acq_scores = np.zeros(len(pool))

        elif len(self.dataset) < self.cfg.min_train_size:
            # 초기 라운드: LHS + boundary seeds 그대로 사용
            indices = list(range(min(self.cfg.tests_per_round, len(pool))))
            acq_scores = np.zeros(len(pool))

        else:
            # Surrogate 재학습 (데이터가 있을 때만 — warm-start는 이미 fitted)
            X_ds = self._dataset_X()
            Y_ds = self._dataset_Y()
            if X_ds is not None:
                self._surrogate.fit(X_ds, Y_ds)

            if not self._surrogate.is_fitted:
                # surrogate 미학습 상태 → 초기 seed 사용
                indices = list(range(min(self.cfg.tests_per_round, len(pool))))
                acq_scores = np.zeros(len(pool))
            else:
                # Acquisition score 계산
                acq_scores = compute_acquisition_scores(
                    X_candidates=X_pool,
                    mutation_list=pool,
                    surrogate=self._surrogate,
                    X_dataset=X_ds,
                    thresholds=self.thresholds,
                    discovered_failure_types=self.discovered_failure_types,
                )

                indices = select_topk_diverse(
                    X_pool, pool, acq_scores,
                    k=self.cfg.tests_per_round,
                    diversity_lambda=self.cfg.diversity_lambda,
                )

        # 3. 선택된 테스트 실행
        round_records = []
        for rank, idx in enumerate(indices):
            params = pool[idx]
            test_id = f"R{round_idx:02d}_T{rank:02d}_{self._run_id}"
            t0 = time.perf_counter()

            oracle_result: OracleResult = self._evaluate(params, test_id)

            elapsed = time.perf_counter() - t0
            fv = build_feature_vector(
                self.sg, params, self._robot_base, self._max_reach
            ).tolist()

            rec = TestRecord(
                test_id=test_id,
                round_idx=round_idx,
                scene_id=self.sg.scene_id,
                mutation_params=params,
                feature_vector=fv,
                margins=oracle_result.margins,
                robustness=oracle_result.robustness,
                verdict=oracle_result.verdict,
                failure_type=oracle_result.failure_type,
                reason=oracle_result.reason,
                recommendation=oracle_result.recommendation,
                acquisition_score=float(acq_scores[idx]),
                elapsed_s=round(elapsed, 3),
            )
            round_records.append(rec)

            if oracle_result.verdict in (Verdict.FAIL, Verdict.BLOCKED):
                self.discovered_failure_types.add(oracle_result.failure_type)

        return round_records

    # ------------------------------------------------------------------
    # 전체 탐색 실행
    # ------------------------------------------------------------------

    def run(self) -> list[TestRecord]:
        print(f"\n{'='*60}")
        print(f"Active Failure Search  mode={self.cfg.mode}  "
              f"scene={self.sg.scene_id}")
        print(f"  rounds={self.cfg.num_rounds}  "
              f"tests/round={self.cfg.tests_per_round}  "
              f"surrogate={self.cfg.surrogate_type}")
        print(f"{'='*60}")

        for round_idx in range(self.cfg.num_rounds):
            t_round = time.perf_counter()
            records = self._run_round(round_idx)
            self.dataset.extend(records)
            elapsed = time.perf_counter() - t_round

            # 라운드 요약
            fails = [r for r in records if r.verdict in (Verdict.FAIL, Verdict.BLOCKED)]
            cum_fails = sum(1 for r in self.dataset
                            if r.verdict in (Verdict.FAIL, Verdict.BLOCKED))
            print(f"\n  [R{round_idx:02d}] {len(records)}개 실행  "
                  f"FAIL/BLOCKED={len(fails)}개  "
                  f"누적={cum_fails}개  "
                  f"({elapsed:.1f}s)")
            if records:
                verdicts = {}
                for r in records:
                    verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
                print(f"        판정: {verdicts}")
                if fails:
                    ftypes = {r.failure_type for r in fails}
                    print(f"        failure_types: {ftypes}")

        print(f"\n  탐색 완료: 총 {len(self.dataset)}개 실행  "
              f"발견 failure_types={self.discovered_failure_types}")

        self._save_log()
        return self.dataset

    # ------------------------------------------------------------------
    # 로그 저장
    # ------------------------------------------------------------------

    def _save_log(self) -> str:
        log_path = Path(self.cfg.log_dir) / f"search_{self._run_id}.json"
        log = {
            "run_id": self._run_id,
            "scene_id": self.sg.scene_id,
            "config": asdict(self.cfg),
            "discovered_failure_types": list(self.discovered_failure_types),
            "total_tests": len(self.dataset),
            "records": [r.to_dict() for r in self.dataset],
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
        print(f"  로그 저장: {log_path}")
        return str(log_path)

    # ------------------------------------------------------------------
    # 결과 요약 통계
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        total = len(self.dataset)
        if total == 0:
            return {}
        fails = [r for r in self.dataset if r.verdict in (Verdict.FAIL, Verdict.BLOCKED)]
        blocked = [r for r in self.dataset if r.verdict == Verdict.BLOCKED]
        warned  = [r for r in self.dataset if r.verdict == Verdict.WARN]
        passed  = [r for r in self.dataset if r.verdict == Verdict.PASS]

        return {
            "total_tests": total,
            "pass":    len(passed),
            "warn":    len(warned),
            "fail":    len(fails) - len(blocked),
            "blocked": len(blocked),
            "failure_discovery_rate": len(fails) / total,
            "unique_failure_types": list(self.discovered_failure_types),
            "num_unique_failure_types": len(self.discovered_failure_types),
        }


# ---------------------------------------------------------------------------
# 비교 실험 실행기
# ---------------------------------------------------------------------------

def run_comparison(
    scene_graph: SceneGraph,
    robot_cfg: dict,
    thresholds: dict,
    base_cfg: SearchConfig,
    pretrained_surrogate: Optional[MultiOutputSurrogate] = None,
) -> dict[str, dict]:
    """Random / Active cold-start / Active warm-start 세 가지를 비교 실행한다."""
    results = {}

    methods = [
        ("random",    SearchConfig(**{**asdict(base_cfg), "mode": "random",
                                     "surrogate_type": "rf"})),
        ("cold",      SearchConfig(**{**asdict(base_cfg), "mode": "cold",
                                     "surrogate_type": "rf"})),
    ]
    if pretrained_surrogate is not None:
        methods.append(
            ("warm", SearchConfig(**{**asdict(base_cfg), "mode": "warm",
                                    "surrogate_type": "rf"}))
        )

    for name, cfg in methods:
        print(f"\n{'─'*50}\n방법: {name}")
        surrogate = pretrained_surrogate if name == "warm" else None
        searcher = ActiveFailureSearch(
            scene_graph, robot_cfg, thresholds, cfg, surrogate
        )
        searcher.run()
        results[name] = searcher.summary()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os
    import sys

    sys.path.insert(0, os.path.dirname(__file__))

    os.environ.setdefault("PYBULLET_MODE", "DIRECT")

    parser = argparse.ArgumentParser(description="Active Failure Search 실행")
    parser.add_argument("--scene", default="data/scene_library/scene_00100.json")
    parser.add_argument("--mode", default="cold", choices=["cold", "warm", "random", "compare"])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--tests-per-round", type=int, default=10)
    parser.add_argument("--surrogate", default="rf", choices=["rf", "gp"])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import scene_builder as sb
    from sim_runner import load_robot_config

    sb.connect()

    sg = SceneGraph.load(args.scene)
    robot_cfg  = load_robot_config("config/robot_config.yaml")
    thresholds = load_thresholds("config/thresholds.yaml")

    cfg = SearchConfig(
        num_rounds=args.rounds,
        tests_per_round=args.tests_per_round,
        surrogate_type=args.surrogate,
        mode=args.mode if args.mode != "compare" else "cold",
        seed=args.seed,
    )

    if args.mode == "compare":
        results = run_comparison(sg, robot_cfg, thresholds, cfg)
        print("\n=== 비교 결과 ===")
        for method, summary in results.items():
            print(f"\n  [{method}]")
            for k, v in summary.items():
                print(f"    {k}: {v}")
    else:
        searcher = ActiveFailureSearch(sg, robot_cfg, thresholds, cfg)
        searcher.run()
        print("\n=== 탐색 요약 ===")
        for k, v in searcher.summary().items():
            print(f"  {k}: {v}")
