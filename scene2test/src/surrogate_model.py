"""surrogate_model.py — Multi-output Surrogate Model.

각 robustness margin을 개별 출력으로 예측한다.
  입력: x = [scene_features(8) | mutation_params_normalized(8)]  → shape (16,)
  출력: margins = [reach, clearance, collision, safety, goal, perception]  → shape (6,)

이렇게 하면:
  - robustness = min(margins)  는 마지막에 취함 (비평활 문제 해소)
  - argmin(margins) = failure_type  이 자동으로 나옴
  - 각 margin마다 불확실성(std)을 추정 가능

구현:
  RFSurrogate   : ExtraTreesRegressor 앙상블 (1차, 혼합형 변수에 강함)
  GPSurrogate   : GaussianProcessRegressor per margin (비교군)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel
from sklearn.preprocessing import StandardScaler

MARGIN_NAMES = ["reach", "clearance", "collision", "safety", "goal", "perception"]
N_MARGINS = len(MARGIN_NAMES)


# ---------------------------------------------------------------------------
# 추상 인터페이스
# ---------------------------------------------------------------------------

class MultiOutputSurrogate(ABC):
    """fit / predict 인터페이스 계약."""

    def __init__(self):
        self.is_fitted = False
        self._scaler = StandardScaler()

    @abstractmethod
    def _fit_impl(self, X: np.ndarray, Y: np.ndarray) -> None: ...

    @abstractmethod
    def _predict_impl(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...

    def fit(self, X: np.ndarray, Y: np.ndarray) -> "MultiOutputSurrogate":
        """학습.

        Args:
            X: (N, 16) 피처 행렬
            Y: (N, 6)  margin 행렬 (MARGIN_NAMES 순서)
        """
        assert X.ndim == 2 and X.shape[1] == 16, f"X shape 오류: {X.shape}"
        assert Y.ndim == 2 and Y.shape[1] == N_MARGINS, f"Y shape 오류: {Y.shape}"
        X_scaled = self._scaler.fit_transform(X)
        self._fit_impl(X_scaled, Y)
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """예측.

        Returns:
            mean: (N, 6) 예측 margin 평균
            std:  (N, 6) 예측 margin 표준편차 (불확실성)
        """
        if not self.is_fitted:
            raise RuntimeError("fit()을 먼저 호출하세요.")
        if X.ndim == 1:
            X = X.reshape(1, -1)
        X_scaled = self._scaler.transform(X)
        return self._predict_impl(X_scaled)

    def predict_robustness(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """robustness = min(margins) 와 그 불확실성을 반환한다.

        Returns:
            rob_mean: (N,)  robustness 예측 평균
            rob_std:  (N,)  binding margin의 std (불확실성 근사)
        """
        mean, std = self.predict(X)               # (N, 6), (N, 6)
        binding_idx = np.argmin(mean, axis=1)     # (N,)
        rob_mean = mean[np.arange(len(mean)), binding_idx]
        rob_std = std[np.arange(len(std)), binding_idx]
        return rob_mean, rob_std

    def predict_failure_prob(self, X: np.ndarray) -> np.ndarray:
        """P(robustness < 0) 를 가우시안 근사로 반환한다. shape (N,)"""
        from scipy.stats import norm
        rob_mean, rob_std = self.predict_robustness(X)
        rob_std = np.clip(rob_std, 1e-6, None)
        return norm.cdf(0, loc=rob_mean, scale=rob_std)


# ---------------------------------------------------------------------------
# RF Surrogate (1차 모델)
# ---------------------------------------------------------------------------

class RFSurrogate(MultiOutputSurrogate):
    """ExtraTrees 앙상블 기반 multi-output surrogate.

    불확실성 = 트리 간 예측 분산.
    혼합형 변수(이진 + 연속)에 강하고 소량 데이터에서 안정적.
    """

    def __init__(self, n_estimators: int = 100, random_state: int = 42):
        super().__init__()
        self.n_estimators = n_estimators
        self.random_state = random_state
        self._models: list[ExtraTreesRegressor] = []

    def _fit_impl(self, X: np.ndarray, Y: np.ndarray) -> None:
        self._models = []
        for j in range(N_MARGINS):
            model = ExtraTreesRegressor(
                n_estimators=self.n_estimators,
                random_state=self.random_state,
                n_jobs=-1,
            )
            model.fit(X, Y[:, j])
            self._models.append(model)

    def _predict_impl(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        N = len(X)
        mean = np.zeros((N, N_MARGINS))
        std  = np.zeros((N, N_MARGINS))

        for j, model in enumerate(self._models):
            # 각 트리의 개별 예측 → mean + std
            tree_preds = np.array([tree.predict(X) for tree in model.estimators_])
            # tree_preds: (n_estimators, N)
            mean[:, j] = tree_preds.mean(axis=0)
            std[:, j]  = tree_preds.std(axis=0)

        return mean, std


# ---------------------------------------------------------------------------
# GP Surrogate (비교군)
# ---------------------------------------------------------------------------

class GPSurrogate(MultiOutputSurrogate):
    """Gaussian Process 기반 multi-output surrogate.

    Matern(nu=2.5) + WhiteKernel.
    소량 데이터에서 불확실성 추정이 이론적으로 정확하나
    혼합형 변수(이진)에는 RF보다 불리.
    """

    def __init__(self, n_restarts: int = 3, random_state: int = 42):
        super().__init__()
        self.n_restarts = n_restarts
        self.random_state = random_state
        self._models: list[GaussianProcessRegressor] = []

    def _fit_impl(self, X: np.ndarray, Y: np.ndarray) -> None:
        kernel = Matern(nu=2.5) + WhiteKernel(noise_level=0.01)
        self._models = []
        for j in range(N_MARGINS):
            gp = GaussianProcessRegressor(
                kernel=kernel,
                n_restarts_optimizer=self.n_restarts,
                random_state=self.random_state,
                normalize_y=True,
            )
            gp.fit(X, Y[:, j])
            self._models.append(gp)

    def _predict_impl(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        N = len(X)
        mean = np.zeros((N, N_MARGINS))
        std  = np.zeros((N, N_MARGINS))
        for j, gp in enumerate(self._models):
            m, s = gp.predict(X, return_std=True)
            mean[:, j] = m
            std[:, j]  = s
        return mean, std


# ---------------------------------------------------------------------------
# 데이터셋 헬퍼
# ---------------------------------------------------------------------------

def build_training_data(
    records: list[dict],
) -> tuple[np.ndarray, np.ndarray]:
    """OracleResult + feature_vector 가 담긴 records 리스트에서 X, Y 행렬을 빌드한다.

    각 record는 다음 키를 포함해야 한다:
      "feature_vector": np.ndarray (16,)
      "margins":        dict with MARGIN_NAMES keys
    """
    X_list, Y_list = [], []
    for rec in records:
        fv = np.array(rec["feature_vector"], dtype=float)
        y  = np.array([rec["margins"][m] for m in MARGIN_NAMES], dtype=float)
        X_list.append(fv)
        Y_list.append(y)
    return np.array(X_list), np.array(Y_list)
