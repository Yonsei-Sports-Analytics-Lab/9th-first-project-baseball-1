"""1차 클러스터링 — 투구 단위 GMM(가우시안 혼합 모델) 적합 모듈.

패스트볼(FF/SI/FC) 투구를 ``ivb_ft``, ``hb_ft``, ``arm_angle`` 로 표준화한 뒤
``K`` 개 성분의 GMM을 적합한다. 각 성분(클러스터)이 "새 구종"이다.

- :meth:`PitchTypeGMM.predict` : 투구별 소속 클러스터 (확률 최대 성분)
- :meth:`PitchTypeGMM.predict_proba` : 투구별 성분 소속 확률

``K`` 는 BIC 로 자동 선택하지 않고 **파라미터로 받는다.** K 탐색은
``notebooks/GMM_pitch_repertoire.ipynb`` 에서 하고, 정한 값을 여기에 넘긴다.

사용 예시
---------
.. code-block:: python

    from src.preprocessing.fit_pitch_gmm import fit_pitch_gmm, summarize_components

    model = fit_pitch_gmm(pitches, n_components=10)
    labels = model.predict(pitches)             # (행 수,)  0 ~ K-1
    print(summarize_components(model, pitches))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 1단계 GMM 기본 피처 (단위가 inch / degree 로 섞여 있어 표준화 필수)
DEFAULT_FEATURES: tuple[str, ...] = ("ivb_ft", "hb_ft", "arm_angle")

#: GMM 적합에 쓸 표본 크기 (전체 ~180만 행을 다 쓰면 느리다).
#: 적합만 표본으로 하고, 클러스터 할당은 모든 투구에 한다.
DEFAULT_FIT_SAMPLE = 200_000

#: 성분마다 자유로운 타원 모양 허용
DEFAULT_COVARIANCE_TYPE = "full"

DEFAULT_N_INIT = 3
DEFAULT_MAX_ITER = 500
DEFAULT_RANDOM_STATE = 42

#: 예측 시 한 번에 처리할 행 수 (K×행 수 크기의 확률 행렬이 생기므로 나눠서 계산)
DEFAULT_PREDICT_BATCH = 500_000

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 모델 컨테이너
# --------------------------------------------------------------------------- #


@dataclass
class PitchTypeGMM:
    """표준화기 + GMM 을 한 묶음으로 다룬다(항상 같은 스케일로 변환하도록)."""

    scaler: StandardScaler
    gmm: GaussianMixture
    features: tuple[str, ...]

    @property
    def n_components(self) -> int:
        return int(self.gmm.n_components)

    @property
    def component_columns(self) -> list[str]:
        """성분(새 구종) 컬럼명: ``C0`` ~ ``C{K-1}``."""
        return [f"C{i}" for i in range(self.n_components)]

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        return self.scaler.transform(frame[list(self.features)].to_numpy(dtype=float))

    def predict_proba(
        self, frame: pd.DataFrame, batch_size: int = DEFAULT_PREDICT_BATCH
    ) -> np.ndarray:
        """각 투구의 성분별 소속 확률 (행 합 = 1)."""
        X = self.transform(frame)
        if len(X) == 0:
            return np.empty((0, self.n_components))
        return np.vstack([
            self.gmm.predict_proba(X[start:start + batch_size])
            for start in range(0, len(X), batch_size)
        ])

    def predict(
        self, frame: pd.DataFrame, batch_size: int = DEFAULT_PREDICT_BATCH
    ) -> np.ndarray:
        """각 투구의 소속 클러스터 번호 (확률 최대 성분, 0 ~ K-1)."""
        X = self.transform(frame)
        if len(X) == 0:
            return np.empty(0, dtype=np.int64)
        return np.concatenate([
            self.gmm.predict(X[start:start + batch_size])
            for start in range(0, len(X), batch_size)
        ]).astype(np.int64)

    def component_centers(self) -> pd.DataFrame:
        """성분 중심을 원래 단위(inch, degree)로 되돌린 표 + 성분 비중."""
        centers = pd.DataFrame(
            self.scaler.inverse_transform(self.gmm.means_),
            columns=list(self.features),
        )
        centers.index.name = "component"
        centers["weight"] = self.gmm.weights_
        return centers


# --------------------------------------------------------------------------- #
# 적합
# --------------------------------------------------------------------------- #


def fit_pitch_gmm(
    train_data: pd.DataFrame,
    n_components: int,
    features: Sequence[str] = DEFAULT_FEATURES,
    fit_sample: int | None = DEFAULT_FIT_SAMPLE,
    covariance_type: str = DEFAULT_COVARIANCE_TYPE,
    n_init: int = DEFAULT_N_INIT,
    max_iter: int = DEFAULT_MAX_ITER,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> PitchTypeGMM:
    """투구 데이터에 표준화 + GMM(``n_components`` 개 성분)을 적합한다.

    Parameters
    ----------
    train_data:
        ``features`` 컬럼을 가진 투구 데이터 (결측 행은 무시).
    n_components:
        새 구종 개수 ``K``.
    fit_sample:
        적합에 쓸 무작위 표본 크기. ``None`` 이면 전체 사용.
    """
    features = tuple(features)
    if n_components < 1:
        raise ValueError(f"n_components 는 1 이상이어야 합니다: {n_components}")
    missing = [column for column in features if column not in train_data.columns]
    if missing:
        raise KeyError(f"학습 데이터에 피처 컬럼이 없습니다: {missing}")

    data = train_data[list(features)].dropna()
    if fit_sample is not None and len(data) > fit_sample:
        data = data.sample(fit_sample, random_state=random_state)
    if len(data) < n_components:
        raise ValueError(
            f"표본({len(data):,}행)이 성분 개수 K={n_components} 보다 적습니다."
        )

    X = data.to_numpy(dtype=float)
    scaler = StandardScaler().fit(X)
    gmm = GaussianMixture(
        n_components=n_components,
        covariance_type=covariance_type,
        n_init=n_init,
        max_iter=max_iter,
        random_state=random_state,
    ).fit(scaler.transform(X))

    if not gmm.converged_:
        logger.warning(
            "GMM 이 max_iter=%d 안에 수렴하지 않았습니다. max_iter 를 늘려 보세요.",
            max_iter,
        )
    logger.info(
        "GMM 적합 완료: K=%d, covariance=%s, 표본 %s행, 수렴=%s (반복 %d회)",
        n_components,
        covariance_type,
        f"{len(X):,}",
        gmm.converged_,
        gmm.n_iter_,
    )
    return PitchTypeGMM(scaler=scaler, gmm=gmm, features=features)


# --------------------------------------------------------------------------- #
# 해석
# --------------------------------------------------------------------------- #


def summarize_components(
    model: PitchTypeGMM,
    frame: pd.DataFrame,
    proba: np.ndarray | None = None,
) -> pd.DataFrame:
    """성분별 중심·비중·투구 수·평균 확신도·주요 기존 구종·좌투 비율 요약표.

    ``proba`` 를 이미 계산해 두었다면 넘겨서 재계산을 피할 수 있다.
    """
    if proba is None:
        proba = model.predict_proba(frame)
    hard = pd.Series(proba.argmax(axis=1), index=frame.index, name="component")
    confidence = pd.Series(proba.max(axis=1), index=frame.index)
    components = range(model.n_components)

    summary = model.component_centers()
    summary["n_pitches"] = hard.value_counts().reindex(components, fill_value=0).astype(int)
    summary["mean_confidence"] = confidence.groupby(hard).mean().reindex(components)

    if "pitch_type" in frame.columns:
        summary["dominant_pitch_type"] = (
            frame["pitch_type"]
            .astype(str)
            .groupby(hard)
            .agg(lambda s: f"{s.mode().iloc[0]} {s.value_counts(normalize=True).iloc[0]:.0%}")
            .reindex(components)
        )
    if "p_throws" in frame.columns:
        summary["left_handed_share"] = (
            frame["p_throws"].astype(str).eq("L").groupby(hard).mean().reindex(components)
        )
    return summary


# --------------------------------------------------------------------------- #
# 저장 / 불러오기
# --------------------------------------------------------------------------- #


def save_model(model: PitchTypeGMM, path: Path) -> None:
    """적합한 모델(표준화기 포함)을 joblib 으로 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    logger.info("GMM 모델 저장: %s", path)


def load_model(path: Path) -> PitchTypeGMM:
    """:func:`save_model` 로 저장한 모델을 불러온다."""
    model = joblib.load(Path(path))
    if not isinstance(model, PitchTypeGMM):
        raise TypeError(f"{path} 는 PitchTypeGMM 이 아닙니다: {type(model).__name__}")
    return model
