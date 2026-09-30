"""1차 클러스터링(GMM) 평가 모듈.

``cluster_pitcher_repertoire.py`` 가 저장한 GMM 모델
(``data/processed/pitch_type_gmm_k{K}.joblib``)과
``{연도}_movement_reconciliation.csv`` 를 읽어, 모든 투구에 클러스터를 다시 붙인 뒤
군집 품질 지표를 출력한다. 모델을 여러 개 주면 한 표로 비교한다.

지표
----
============================ ===== ==============================================
지표                          방향   의미
============================ ===== ==============================================
``silhouette``               ↑     군집 내 응집 vs 군집 간 분리 (-1~1). O(n²) 이라
                                   무작위 표본으로 여러 번 계산해 평균±표준편차
``davies_bouldin``           ↓     군집 간 유사도 평균 (0 에 가까울수록 좋음)
``calinski_harabasz``        ↑     군집 간 분산 / 군집 내 분산
``avg_log_likelihood``       ↑     투구 1개당 평균 로그우도 (GMM ``score``)
``bic`` / ``aic``            ↓     정보량 기준 — K 가 다른 모델끼리 비교할 때
``mean_max_proba``           ↑     투구별 최대 소속 확률의 평균 (할당 확신도)
``ambiguous_share``          ↓     최대 소속 확률이 기준(기본 0.6) 미만인 투구 비율
``normalized_entropy``       ↓     소속 확률 엔트로피 / log K (0=확실, 1=완전 모호)
``ari_vs_pitch_type``        참고   기존 ``pitch_type`` 과의 일치도 (Adjusted Rand)
``nmi_vs_pitch_type``        참고   기존 ``pitch_type`` 과의 정규화 상호정보량
============================ ===== ==============================================

모든 지표는 GMM 이 적합된 공간(모델의 표준화기로 변환한 피처)에서 계산한다.
``ari``/``nmi`` 는 높다고 좋은 것이 아니다 — 1 에 가까우면 기존 FF/SI/FC 를
그대로 재현했다는 뜻이고, 낮으면 기존 라벨과 다르게 나눴다는 뜻이다.

CLI 사용 예시
-------------
.. code-block:: bash

    # K=10 모델 평가 (data/processed/pitch_type_gmm_k10.joblib)
    python src/preprocessing/evaluate_pitch_gmm.py --k 10

    # 여러 K 비교
    python src/preprocessing/evaluate_pitch_gmm.py --k 3 6 10

    # 모델 경로 직접 지정 + 결과를 JSON 으로도 저장
    python src/preprocessing/evaluate_pitch_gmm.py \
        --model data/processed/pitch_type_gmm_k6.joblib \
        --output data/processed/gmm_metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_samples,
)

#: 프로젝트 루트 (src/preprocessing/<이 파일> 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.preprocessing.fit_pitch_gmm import (  # noqa: E402
    PitchTypeGMM,
    default_model_path,
    load_model,
)
from src.preprocessing.load_movement_data import (  # noqa: E402
    DEFAULT_CHUNKSIZE,
    DEFAULT_PROCESSED_DIR,
    find_movement_files,
    load_pitch_data,
)

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 실루엣 계산 표본 크기 (거리 행렬이 n² 이라 전체 180만 행은 불가능)
DEFAULT_SILHOUETTE_SAMPLE = 30_000

#: 실루엣 표본 반복 횟수 (표본에 따른 흔들림을 보기 위해)
DEFAULT_SILHOUETTE_REPEATS = 3

#: 이 값 미만의 최대 소속 확률을 가진 투구를 "경계(모호한) 투구"로 본다
DEFAULT_AMBIGUOUS_THRESHOLD = 0.6

DEFAULT_RANDOM_STATE = 42

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 결과 자료구조
# --------------------------------------------------------------------------- #


@dataclass
class GMMEvaluation:
    """모델 하나의 평가 결과."""

    model_path: str
    k: int
    n_pitches: int
    silhouette: float
    silhouette_std: float
    silhouette_sample: int
    davies_bouldin: float
    calinski_harabasz: float
    avg_log_likelihood: float
    bic: float
    aic: float
    mean_max_proba: float
    ambiguous_share: float
    normalized_entropy: float
    ari_vs_pitch_type: float
    nmi_vs_pitch_type: float
    clusters: pd.DataFrame = field(repr=False)

    def metrics(self) -> dict[str, float | int | str]:
        """``clusters`` 표를 뺀 스칼라 지표."""
        data = asdict(self)
        data.pop("clusters")
        return data

    def to_json(self) -> dict:
        data = self.metrics()
        data["clusters"] = json.loads(
            self.clusters.reset_index().to_json(orient="records", force_ascii=False)
        )
        return data


# --------------------------------------------------------------------------- #
# 지표 계산
# --------------------------------------------------------------------------- #


def sampled_silhouette(
    X: np.ndarray,
    labels: np.ndarray,
    sample_size: int = DEFAULT_SILHOUETTE_SAMPLE,
    repeats: int = DEFAULT_SILHOUETTE_REPEATS,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> tuple[float, float, pd.Series]:
    """무작위 표본으로 실루엣을 ``repeats`` 번 계산한다.

    Returns
    -------
    (평균, 표준편차, 클러스터별 평균 실루엣)
    """
    rng = np.random.default_rng(random_state)
    size = min(sample_size, len(X))
    scores: list[float] = []
    per_sample: list[pd.DataFrame] = []

    for _ in range(max(1, repeats)):
        index = rng.choice(len(X), size=size, replace=False)
        sample_labels = labels[index]
        if len(np.unique(sample_labels)) < 2:
            continue
        values = silhouette_samples(X[index], sample_labels)
        scores.append(float(values.mean()))
        per_sample.append(pd.DataFrame({"cluster": sample_labels, "silhouette": values}))

    if not scores:
        return float("nan"), float("nan"), pd.Series(dtype=float)

    per_cluster = pd.concat(per_sample).groupby("cluster")["silhouette"].mean()
    std = float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0
    return float(np.mean(scores)), std, per_cluster


def cluster_table(
    model: PitchTypeGMM,
    pitches: pd.DataFrame,
    proba: np.ndarray,
    labels: np.ndarray,
    silhouette_by_cluster: pd.Series,
    ambiguous_threshold: float,
) -> pd.DataFrame:
    """클러스터별 중심·크기·확신도·실루엣·주요 기존 구종."""
    k = model.n_components
    components = range(k)
    labels_s = pd.Series(labels, index=pitches.index)
    max_proba = pd.Series(proba.max(axis=1), index=pitches.index)

    table = model.component_centers().rename(columns={"weight": "gmm_weight"})
    counts = labels_s.value_counts().reindex(components, fill_value=0)
    table["n_pitches"] = counts.astype("int64")
    table["share"] = counts / max(len(labels), 1)
    table["mean_max_proba"] = max_proba.groupby(labels_s).mean().reindex(components)
    table["ambiguous_share"] = (
        max_proba.lt(ambiguous_threshold).groupby(labels_s).mean().reindex(components)
    )
    table["silhouette"] = silhouette_by_cluster.reindex(components)

    if "pitch_type" in pitches.columns:
        pitch_type = pitches["pitch_type"].astype(str)
        table["dominant_pitch_type"] = (
            pitch_type.groupby(labels_s)
            .agg(lambda s: f"{s.mode().iloc[0]} {s.value_counts(normalize=True).iloc[0]:.0%}")
            .reindex(components)
        )
    table.index.name = "cluster"
    return table


def evaluate_model(
    model: PitchTypeGMM,
    pitches: pd.DataFrame,
    model_path: str = "",
    silhouette_sample: int = DEFAULT_SILHOUETTE_SAMPLE,
    silhouette_repeats: int = DEFAULT_SILHOUETTE_REPEATS,
    ambiguous_threshold: float = DEFAULT_AMBIGUOUS_THRESHOLD,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> GMMEvaluation:
    """모든 투구에 클러스터를 붙이고 품질 지표를 계산한다."""
    missing = [column for column in model.features if column not in pitches.columns]
    if missing:
        raise KeyError(f"투구 데이터에 모델 피처가 없습니다: {missing}")

    data = pitches.dropna(subset=list(model.features))
    X = model.transform(data)
    proba = model.predict_proba(data)
    labels = proba.argmax(axis=1)
    k = model.n_components
    n_labels = len(np.unique(labels))
    logger.info("[K=%d] 투구 %s개에 클러스터 할당 (실제 사용된 클러스터 %d개)",
                k, f"{len(X):,}", n_labels)

    silhouette, silhouette_std, silhouette_by_cluster = sampled_silhouette(
        X, labels, silhouette_sample, silhouette_repeats, random_state
    )
    separable = n_labels >= 2
    davies_bouldin = float(davies_bouldin_score(X, labels)) if separable else float("nan")
    calinski = float(calinski_harabasz_score(X, labels)) if separable else float("nan")

    max_proba = proba.max(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        entropy = -np.sum(np.where(proba > 0, proba * np.log(proba), 0.0), axis=1)
    normalized_entropy = float(entropy.mean() / np.log(k)) if k > 1 else 0.0

    if "pitch_type" in data.columns:
        pitch_type = data["pitch_type"].astype(str).to_numpy()
        ari = float(adjusted_rand_score(pitch_type, labels))
        nmi = float(normalized_mutual_info_score(pitch_type, labels))
    else:
        ari = nmi = float("nan")

    result = GMMEvaluation(
        model_path=str(model_path),
        k=k,
        n_pitches=int(len(X)),
        silhouette=silhouette,
        silhouette_std=silhouette_std,
        silhouette_sample=int(min(silhouette_sample, len(X))),
        davies_bouldin=davies_bouldin,
        calinski_harabasz=calinski,
        avg_log_likelihood=float(model.gmm.score(X)),
        bic=float(model.gmm.bic(X)),
        aic=float(model.gmm.aic(X)),
        mean_max_proba=float(max_proba.mean()),
        ambiguous_share=float((max_proba < ambiguous_threshold).mean()),
        normalized_entropy=normalized_entropy,
        ari_vs_pitch_type=ari,
        nmi_vs_pitch_type=nmi,
        clusters=cluster_table(
            model, data, proba, labels, silhouette_by_cluster, ambiguous_threshold
        ),
    )
    return result


# --------------------------------------------------------------------------- #
# 출력
# --------------------------------------------------------------------------- #

#: 요약표에 보여줄 지표 (라벨, 방향)
METRIC_LABELS: dict[str, str] = {
    "k": "K",
    "n_pitches": "투구 수",
    "silhouette": "실루엣 ↑",
    "silhouette_std": "실루엣 표준편차",
    "davies_bouldin": "데이비스-볼딘 ↓",
    "calinski_harabasz": "칼린스키-하라바즈 ↑",
    "avg_log_likelihood": "평균 로그우도 ↑",
    "bic": "BIC ↓",
    "aic": "AIC ↓",
    "mean_max_proba": "평균 최대확률 ↑",
    "ambiguous_share": "경계 투구 비율 ↓",
    "normalized_entropy": "정규화 엔트로피 ↓",
    "ari_vs_pitch_type": "ARI vs pitch_type",
    "nmi_vs_pitch_type": "NMI vs pitch_type",
}


def comparison_table(results: Sequence[GMMEvaluation]) -> pd.DataFrame:
    """모델별 스칼라 지표를 한 표로 (행 = 지표, 열 = 모델)."""
    columns = {}
    for result in results:
        name = Path(result.model_path).stem or f"K={result.k}"
        metrics = result.metrics()
        columns[name] = [metrics[key] for key in METRIC_LABELS]
    return pd.DataFrame(columns, index=list(METRIC_LABELS.values()))


def format_report(results: Sequence[GMMEvaluation], ambiguous_threshold: float) -> str:
    """콘솔에 출력할 보고서 문자열."""
    lines: list[str] = []
    with pd.option_context(
        "display.width", 180,
        "display.max_columns", 30,
        "display.float_format", lambda v: f"{v:,.4f}",
    ):
        lines.append("=" * 72)
        lines.append("1차 클러스터링(GMM) 평가 요약")
        lines.append("=" * 72)
        table = comparison_table(results).astype(object)
        for label in ("K", "투구 수"):
            table.loc[label] = [f"{int(v):,}" for v in table.loc[label]]
        lines.append(table.to_string())
        lines.append(
            f"\n* 실루엣은 {results[0].silhouette_sample:,}개 표본으로 반복 계산한 평균입니다."
            f"\n* 경계 투구 = 최대 소속 확률 < {ambiguous_threshold:.2f}"
            "\n* ARI/NMI 는 기존 FF/SI/FC 와의 일치도(높다고 좋은 것은 아님)"
        )

        for result in results:
            lines.append("\n" + "-" * 72)
            lines.append(f"[K={result.k}] 클러스터별 지표 — {result.model_path}")
            lines.append("-" * 72)
            clusters = result.clusters.copy()
            clusters["share"] = clusters["share"].map(lambda v: f"{v:.1%}")
            clusters["gmm_weight"] = clusters["gmm_weight"].map(lambda v: f"{v:.1%}")
            clusters["ambiguous_share"] = clusters["ambiguous_share"].map(lambda v: f"{v:.1%}")
            clusters["n_pitches"] = clusters["n_pitches"].map(lambda v: f"{v:,}")
            lines.append(clusters.round(2).to_string())
    return "\n".join(lines)


def save_metrics_json(results: Sequence[GMMEvaluation], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [result.to_json() for result in results]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    logger.info("지표 저장: %s", path)
    return path


# --------------------------------------------------------------------------- #
# 전체 실행
# --------------------------------------------------------------------------- #


def run(
    model_paths: Sequence[Path],
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    years: Iterable[int] | None = None,
    silhouette_sample: int = DEFAULT_SILHOUETTE_SAMPLE,
    silhouette_repeats: int = DEFAULT_SILHOUETTE_REPEATS,
    ambiguous_threshold: float = DEFAULT_AMBIGUOUS_THRESHOLD,
    chunksize: int = DEFAULT_CHUNKSIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> list[GMMEvaluation]:
    """모델들을 불러와 같은 투구 데이터로 평가한다(CSV 는 한 번만 읽는다)."""
    if not model_paths:
        raise ValueError("평가할 모델 경로가 없습니다.")
    for path in model_paths:
        if not Path(path).is_file():
            raise FileNotFoundError(
                f"모델 파일이 없습니다: {path}\n"
                "먼저 cluster_pitcher_repertoire.py 를 실행해 모델을 저장하세요 "
                "(기본 저장 경로: data/processed/pitch_type_gmm_k{K}.joblib)."
            )
    models = [(Path(path), load_model(path)) for path in model_paths]

    # 모든 모델의 피처를 합쳐 한 번에 읽는다
    features = list(dict.fromkeys(f for _, model in models for f in model.features))
    files = find_movement_files(processed_dir, years)
    pitches = load_pitch_data(
        files,
        features=features,
        chunksize=chunksize,
        columns=[*features, "pitch_type", "game_year"],
    )

    results = []
    for path, model in models:
        results.append(
            evaluate_model(
                model,
                pitches,
                model_path=str(path),
                silhouette_sample=silhouette_sample,
                silhouette_repeats=silhouette_repeats,
                ambiguous_threshold=ambiguous_threshold,
                random_state=random_state,
            )
        )
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="저장된 GMM 모델과 무브먼트 CSV 로 1차 클러스터링 품질 지표를 출력합니다.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--k", type=int, nargs="+", default=None,
        help="평가할 K (<processed-dir>/pitch_type_gmm_k{K}.joblib 을 읽음). 기본값: 10",
    )
    source.add_argument(
        "--model", type=Path, nargs="+", default=None,
        help="평가할 모델 파일 경로 (여러 개 가능)",
    )
    parser.add_argument(
        "--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR,
        help=f"CSV·모델 디렉토리 (기본값: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--years", type=int, nargs="+", default=None,
        help="평가에 쓸 연도 (기본값: 모든 연도)",
    )
    parser.add_argument(
        "--silhouette-sample", type=int, default=DEFAULT_SILHOUETTE_SAMPLE,
        help=f"실루엣 표본 크기 (기본값: {DEFAULT_SILHOUETTE_SAMPLE:,})",
    )
    parser.add_argument(
        "--silhouette-repeats", type=int, default=DEFAULT_SILHOUETTE_REPEATS,
        help=f"실루엣 표본 반복 횟수 (기본값: {DEFAULT_SILHOUETTE_REPEATS})",
    )
    parser.add_argument(
        "--ambiguous-threshold", type=float, default=DEFAULT_AMBIGUOUS_THRESHOLD,
        help=f"경계 투구 기준 최대 소속 확률 (기본값: {DEFAULT_AMBIGUOUS_THRESHOLD})",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="지표를 JSON 으로도 저장할 경로 (선택)",
    )
    parser.add_argument(
        "--chunksize", type=int, default=DEFAULT_CHUNKSIZE,
        help=f"한 번에 읽을 행 수 (기본값: {DEFAULT_CHUNKSIZE:,})",
    )
    parser.add_argument(
        "--random-state", type=int, default=DEFAULT_RANDOM_STATE,
        help=f"난수 시드 (기본값: {DEFAULT_RANDOM_STATE})",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본값: INFO)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.model:
        model_paths = list(args.model)
    else:
        model_paths = [default_model_path(k, args.processed_dir) for k in (args.k or [10])]

    results = run(
        model_paths=model_paths,
        processed_dir=args.processed_dir,
        years=args.years,
        silhouette_sample=args.silhouette_sample,
        silhouette_repeats=args.silhouette_repeats,
        ambiguous_threshold=args.ambiguous_threshold,
        chunksize=args.chunksize,
        random_state=args.random_state,
    )

    print(format_report(results, args.ambiguous_threshold))
    if args.output is not None:
        save_metrics_json(results, args.output)
        print(f"\n저장: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
