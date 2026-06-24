"""acquisition.py — Acquisition Function.

다음에 실행할 테스트 장면을 선택하는 기준 점수를 계산한다.

A(z) =
    w1 * P(robustness < 0)       실패 가능성
  + w2 * uncertainty              예측 불확실성
  + w3 * safety_priority          human_zone 근접 여부
  + w4 * novelty_score            기존 테스트와 다양성
  - w5 * redundancy_score         중복 페널티

기본 가중치: w1=0.35, w2=0.25, w3=0.20, w4=0.15, w5=0.05
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from surrogate_model import MultiOutputSurrogate, MARGIN_NAMES

# ---------------------------------------------------------------------------
# 기본 가중치
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "w_fail":       0.35,
    "w_uncertainty": 0.25,
    "w_safety":     0.20,
    "w_novelty":    0.15,
    "w_redundancy": 0.05,
}


# ---------------------------------------------------------------------------
# 개별 스코어 컴포넌트
# ---------------------------------------------------------------------------

def _failure_probability(
    surrogate: MultiOutputSurrogate,
    X: np.ndarray,
) -> np.ndarray:
    """P(robustness < 0) 배치 계산. shape (N,)"""
    return surrogate.predict_failure_prob(X)


def _uncertainty(
    surrogate: MultiOutputSurrogate,
    X: np.ndarray,
) -> np.ndarray:
    """binding margin의 표준편차 (정규화). shape (N,)"""
    _, std = surrogate.predict(X)
    # binding margin(가장 낮은 margin)의 std
    mean, _ = surrogate.predict(X)
    binding_idx = np.argmin(mean, axis=1)
    unc = std[np.arange(len(std)), binding_idx]
    return unc


def _safety_priority(
    mutation_list: list[dict],
    thresholds: dict,
) -> np.ndarray:
    """human_zone_y, human_zone_x 파라미터가 있으면 safety 가중치를 올린다.

    human_zone_x/y가 모두 파라미터에 있을 때 = 인간 안전 테스트로 간주.
    """
    scores = []
    safety_dist = thresholds["safety"]["safety_distance"]
    for params in mutation_list:
        hz_x = params.get("human_zone_x")
        hz_y = params.get("human_zone_y")
        if hz_x is not None and hz_y is not None:
            scores.append(1.0)
        else:
            scores.append(0.0)
    return np.array(scores)


def _novelty_score(
    X_candidates: np.ndarray,
    X_dataset: Optional[np.ndarray],
    k: int = 5,
) -> np.ndarray:
    """기존 데이터셋과의 최소 거리 (탐색 다양성). shape (N,)

    데이터셋이 없으면 1.0 반환.
    """
    if X_dataset is None or len(X_dataset) == 0:
        return np.ones(len(X_candidates))

    # 각 후보에 대해 dataset 내 k-NN 평균 거리 계산
    scores = []
    for xc in X_candidates:
        dists = np.linalg.norm(X_dataset - xc, axis=1)
        k_nearest = np.sort(dists)[:k]
        scores.append(k_nearest.mean())

    scores = np.array(scores)
    # 정규화 [0, 1]
    max_d = scores.max()
    if max_d > 1e-8:
        scores = scores / max_d
    return scores


def _redundancy_score(
    X_candidates: np.ndarray,
    X_dataset: Optional[np.ndarray],
) -> np.ndarray:
    """기존 데이터셋과 너무 가까운 후보 페널티. shape (N,)"""
    if X_dataset is None or len(X_dataset) == 0:
        return np.zeros(len(X_candidates))

    scores = []
    for xc in X_candidates:
        min_dist = np.min(np.linalg.norm(X_dataset - xc, axis=1))
        # 매우 가까우면(< 0.05) 높은 페널티
        scores.append(max(0.0, 1.0 - min_dist / 0.05))
    return np.array(scores)


# ---------------------------------------------------------------------------
# Failure Type Coverage Bonus
# ---------------------------------------------------------------------------

def _coverage_bonus(
    mutation_list: list[dict],
    discovered_failure_types: set[str],
) -> np.ndarray:
    """아직 발견하지 못한 실패 유형을 유발할 가능성이 높은 후보에 보너스.

    tray_occupied=1 → destination_occupied 유도
    occlusion_ratio>0.5 → perception_uncertainty 유도
    human_zone 있음 → human_risk 유도
    """
    all_types = {
        "unreachable", "insufficient_clearance", "path_collision",
        "human_risk", "destination_occupied", "perception_uncertainty",
    }
    missing = all_types - discovered_failure_types
    scores = []
    for params in mutation_list:
        bonus = 0.0
        if "destination_occupied" in missing and round(params.get("tray_occupied", 0)) == 1:
            bonus += 0.3
        if "perception_uncertainty" in missing and params.get("occlusion_ratio", 0) > 0.45:
            bonus += 0.3
        if "human_risk" in missing and params.get("human_zone_x") is not None:
            bonus += 0.3
        if "insufficient_clearance" in missing and params.get("obstacle_dist_to_target", 1.0) < 0.07:
            bonus += 0.2
        scores.append(min(bonus, 1.0))
    return np.array(scores)


# ---------------------------------------------------------------------------
# 메인 acquisition score 계산
# ---------------------------------------------------------------------------

def compute_acquisition_scores(
    X_candidates: np.ndarray,
    mutation_list: list[dict],
    surrogate: MultiOutputSurrogate,
    X_dataset: Optional[np.ndarray],
    thresholds: dict,
    discovered_failure_types: Optional[set[str]] = None,
    weights: Optional[dict] = None,
) -> np.ndarray:
    """후보 전체의 acquisition score를 배치로 계산한다. shape (N,)"""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    disc = discovered_failure_types or set()

    prob_fail = _failure_probability(surrogate, X_candidates)
    unc       = _uncertainty(surrogate, X_candidates)
    safety    = _safety_priority(mutation_list, thresholds)
    novelty   = _novelty_score(X_candidates, X_dataset)
    redundancy = _redundancy_score(X_candidates, X_dataset)
    coverage  = _coverage_bonus(mutation_list, disc)

    scores = (
        w["w_fail"]       * prob_fail
      + w["w_uncertainty"] * unc
      + w["w_safety"]     * safety
      + w["w_novelty"]    * novelty
      - w["w_redundancy"] * redundancy
      + 0.10              * coverage   # coverage bonus는 고정 가중치
    )
    return scores


# ---------------------------------------------------------------------------
# Top-K with diversity (greedy)
# ---------------------------------------------------------------------------

def select_topk_diverse(
    X_candidates: np.ndarray,
    mutation_list: list[dict],
    scores: np.ndarray,
    k: int = 10,
    diversity_lambda: float = 0.3,
) -> list[int]:
    """Greedy submodular selection: score + diversity를 동시에 고려해 k개 인덱스를 반환한다.

    매 단계에서 (score + λ * min_dist_to_selected) 가 가장 높은 후보를 선택.
    """
    remaining = list(range(len(X_candidates)))
    selected = []
    selected_X: list[np.ndarray] = []

    for _ in range(min(k, len(remaining))):
        if not remaining:
            break

        if not selected_X:
            # 첫 번째: 순수 score 최고
            best_idx_in_remaining = int(np.argmax([scores[i] for i in remaining]))
            chosen = remaining[best_idx_in_remaining]
        else:
            sel_arr = np.array(selected_X)
            combined = []
            for idx in remaining:
                min_dist = np.min(np.linalg.norm(sel_arr - X_candidates[idx], axis=1))
                combined.append(scores[idx] + diversity_lambda * min_dist)
            best_idx_in_remaining = int(np.argmax(combined))
            chosen = remaining[best_idx_in_remaining]

        selected.append(chosen)
        selected_X.append(X_candidates[chosen])
        remaining.remove(chosen)

    return selected
