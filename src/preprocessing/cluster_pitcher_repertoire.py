"""투수-시즌별 1차 클러스터 집계 파이프라인 모듈.

파이프라인
----------
1. **로드** (:mod:`load_movement_data`)
   ``{연도}_movement_reconciliation.csv`` 에서 **모든 연도의 모든 투구** 를 읽는다.
2. **1차 클러스터링** (:mod:`fit_pitch_gmm`)
   ``ivb_ft, hb_ft, arm_angle`` 로 GMM(``K`` 개 성분)을 적합하고, 모든 투구에
   소속 클러스터(확률 최대 성분)를 붙인다. ``K`` 는 인자로 받는다.
3. **투수-시즌 집계** (:func:`summarize_pitcher_seasons`)
   ``(pitcher, game_year)`` 로 묶어서

   - ``cluster`` : 그 투구들이 가장 많이 속한 1차 클러스터 (최빈값)
   - ``average_velocity`` : **주 패스트볼**(그 시즌 FF/SI/FC 중 가장 많이 던진 구종)의 평균 구속
     (``release_speed``, mph). ``src/utils/llm_client.py`` 의 ``primary_fastball`` 과 같은 기준.

   를 구한다. 투구 수가 ``min_pitches`` (기본 200) 미만인 투수-시즌은 제외한다.
4. **저장** (:func:`save_cluster_json`)
   ``data/processed/pitcher_repertoire_clusters_k{K}.json`` 에
   ``{MLB ID: {연도: {...}}}`` 형식으로 저장한다::

       {
         "660271": {
           "2023": { "average_velocity": 100.0, "cluster": 10 },
           ...
         },
         ...
       }

   - 키는 Statcast ``pitcher`` 컬럼(MLBAM ID)이다. 이름과 달리 동명이인 문제가 없다.

CLI 사용 예시
-------------
.. code-block:: bash

    # 기본값: K=10, 모든 연도
    python src/preprocessing/cluster_pitcher_repertoire.py

    # K 지정
    python src/preprocessing/cluster_pitcher_repertoire.py --k 7

    # 이미 저장한 GMM 모델로 할당만 (재적합 없음)
    python src/preprocessing/cluster_pitcher_repertoire.py \
        --model-in data/processed/pitch_type_gmm_k10.joblib

    # 특정 연도만 사용 + 결과 JSON 경로 지정
    python src/preprocessing/cluster_pitcher_repertoire.py --k 6 \
        --years 2023 2024 2025 \
        --output data/processed/pitcher_repertoire_clusters_k6.json

적합한 GMM 모델은 기본으로 ``data/processed/pitch_type_gmm_k{K}.joblib`` 에
저장된다(``evaluate_pitch_gmm.py`` 가 이 파일을 읽는다). ``--model-out`` 으로
경로를 바꾸거나 ``--no-save-model`` 로 저장을 끌 수 있다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

#: 프로젝트 루트 (src/preprocessing/<이 파일> 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# `python src/preprocessing/cluster_pitcher_repertoire.py` 로 직접 실행해도
# `src.` 패키지 경로로 임포트할 수 있도록 프로젝트 루트를 경로에 추가한다.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.preprocessing.fit_pitch_gmm import (  # noqa: E402
    DEFAULT_FIT_SAMPLE,
    PitchTypeGMM,
    default_model_path,
    fit_pitch_gmm,
    load_model,
    save_model,
    summarize_components,
)
from src.preprocessing.load_movement_data import (  # noqa: E402
    DEFAULT_CHUNKSIZE,
    DEFAULT_FEATURES,
    DEFAULT_PROCESSED_DIR,
    VELOCITY_COLUMN,
    find_movement_files,
    load_pitch_data,
)

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 1차 클러스터(GMM 성분) 개수 K
DEFAULT_K = 10

#: 이보다 적게 던진 투수-시즌은 제외
DEFAULT_MIN_PITCHES = 200

#: 결과 JSON 파일명 (형식은 data/processed/data_description.json 참고)
OUTPUT_FILE_TEMPLATE = "pitcher_repertoire_clusters_k{k}.json"

#: 평균 구속 반올림 자릿수
VELOCITY_DECIMALS = 1

DEFAULT_RANDOM_STATE = 42

logger = logging.getLogger(__name__)


def default_output_path(k: int, processed_dir: Path = DEFAULT_PROCESSED_DIR) -> Path:
    """K 에 대응하는 기본 결과 경로 (``pitcher_repertoire_clusters_k{K}.json``)."""
    return Path(processed_dir) / OUTPUT_FILE_TEMPLATE.format(k=int(k))


# --------------------------------------------------------------------------- #
# 3. 투수-시즌 집계
# --------------------------------------------------------------------------- #


def summarize_pitcher_seasons(
    pitches: pd.DataFrame,
    labels: np.ndarray,
    n_clusters: int,
) -> pd.DataFrame:
    """투구를 ``(pitcher, game_year)`` 로 묶어 최빈 1차 클러스터와 주 패스트볼 평균 구속을 구한다.

    Parameters
    ----------
    pitches:
        ``pitcher, game_year, pitch_type, player_name, p_throws, release_speed`` 를 가진 투구.
    labels:
        ``pitches`` 와 같은 길이의 1차 클러스터 번호 (0 ~ ``n_clusters``-1).

    Returns
    -------
    pd.DataFrame
        ``pitcher, player_name, p_throws, game_year, n_pitches, primary_pitch_type,
        average_velocity, cluster, cluster_share, n_C0 ... n_C{K-1}``

        - ``primary_pitch_type`` : 주 패스트볼 — 가장 많이 던진 구종 (동률이면 코드 알파벳순 앞쪽)
        - ``average_velocity`` : 주 패스트볼의 평균 ``release_speed`` (구속 결측은 제외)
        - ``cluster`` : 가장 많은 투구가 속한 클러스터 (동률이면 번호가 작은 쪽)
        - ``cluster_share`` : 그 클러스터에 속한 투구 비율
        - ``n_C*`` : 클러스터별 투구 수
    """
    if len(labels) != len(pitches):
        raise ValueError(f"labels 길이({len(labels)})가 투구 수({len(pitches)})와 다릅니다.")

    keys = ["pitcher", "game_year"]
    frame = pitches[keys + [VELOCITY_COLUMN]].assign(cluster=np.asarray(labels))

    # 클러스터별 투구 수 (투수-시즌 × K)
    counts = (
        frame.groupby(keys + ["cluster"]).size()
        .unstack("cluster", fill_value=0)
        .reindex(columns=range(n_clusters), fill_value=0)
    )
    count_values = counts.to_numpy()
    n_pitches = count_values.sum(axis=1)
    mode = count_values.argmax(axis=1)  # 동률이면 앞(작은 번호)을 고른다

    seasons = pd.DataFrame(index=counts.index)
    seasons["n_pitches"] = n_pitches.astype("int64")
    # 주 패스트볼(가장 많이 던진 구종)과 그 구종의 평균 구속.
    # FF/SI/FC 를 섞어 평균 내면 커터가 섞인 투수의 구속이 실제보다 낮게 잡히므로 구종별로 따로 본다.
    by_type = (
        pitches[keys + ["pitch_type", VELOCITY_COLUMN]]
        .astype({"pitch_type": str})
        .groupby(keys + ["pitch_type"])[VELOCITY_COLUMN]
        .agg(n="size", velocity="mean")
        .reset_index()
        .sort_values(keys + ["n", "pitch_type"], ascending=[True, True, False, True])
    )
    primary = by_type.drop_duplicates(keys, keep="first").set_index(keys)
    seasons["primary_pitch_type"] = primary["pitch_type"]
    seasons["average_velocity"] = primary["velocity"]
    seasons["cluster"] = mode.astype("int64")
    seasons["cluster_share"] = count_values[np.arange(len(mode)), mode] / n_pitches
    for k in range(n_clusters):
        seasons[f"n_C{k}"] = count_values[:, k].astype("int64")
    seasons = seasons.reset_index()

    # 투수 이름·손 (같은 투수의 마지막 표기 사용)
    identities = (
        pitches[["pitcher", "player_name", "p_throws"]]
        .drop_duplicates("pitcher", keep="last")
        .astype({"player_name": object, "p_throws": object})
        .set_index("pitcher")
    )
    seasons = seasons.join(identities, on="pitcher")

    ordered = [
        "pitcher", "player_name", "p_throws", "game_year", "n_pitches",
        "primary_pitch_type", "average_velocity", "cluster", "cluster_share",
        *[f"n_C{k}" for k in range(n_clusters)],
    ]
    seasons = seasons[ordered].sort_values(["pitcher", "game_year"])
    logger.info("투수-시즌 %s개 집계", f"{len(seasons):,}")
    return seasons.reset_index(drop=True)


def filter_min_pitches(seasons: pd.DataFrame, min_pitches: int) -> pd.DataFrame:
    """투구 수가 ``min_pitches`` 미만인 투수-시즌을 제외한다."""
    kept = seasons[seasons["n_pitches"] >= min_pitches].reset_index(drop=True)
    logger.info(
        "%d구 이상 투수-시즌: %s / %s개 (투수 %s명)",
        min_pitches,
        f"{len(kept):,}",
        f"{len(seasons):,}",
        f"{kept['pitcher'].nunique():,}",
    )
    return kept


# --------------------------------------------------------------------------- #
# 4. JSON 저장 ({MLB ID: {연도: {...}}})
# --------------------------------------------------------------------------- #


def build_description_payload(
    seasons: pd.DataFrame,
    velocity_decimals: int = VELOCITY_DECIMALS,
) -> dict[str, dict[str, dict[str, float | int | None]]]:
    """``{MLB ID: {연도: {"average_velocity": ..., "cluster": ...}}}`` 딕셔너리.

    키는 Statcast ``pitcher`` 컬럼(MLBAM ID)을 문자열로 쓴다(JSON 키는 문자열만 가능).
    MLB ID 오름차순, 연도 오름차순으로 정렬한다.
    """
    frame = seasons.sort_values(["pitcher", "game_year"])

    payload: dict[str, dict[str, dict[str, float | int | None]]] = {}
    for row in frame.itertuples(index=False):
        velocity = row.average_velocity
        payload.setdefault(str(int(row.pitcher)), {})[str(int(row.game_year))] = {
            "average_velocity": (
                None if pd.isna(velocity) else round(float(velocity), velocity_decimals)
            ),
            "cluster": int(row.cluster),
        }
    return payload


def dumps_description(payload: Mapping[str, Mapping[str, Mapping]]) -> str:
    """시즌 레코드를 한 줄로 두는 배치(data_description.json 과 같은 모양)로 직렬화한다."""
    if not payload:
        return "{}\n"

    def inline(record: Mapping) -> str:
        body = json.dumps(record, ensure_ascii=False, separators=(", ", ": "))[1:-1]
        return f"{{ {body} }}"

    lines = ["{"]
    players = list(payload.items())
    for i, (name, seasons) in enumerate(players):
        lines.append(f"  {json.dumps(name, ensure_ascii=False)}: {{")
        items = list(seasons.items())
        for j, (year, record) in enumerate(items):
            comma = "," if j < len(items) - 1 else ""
            lines.append(f"    {json.dumps(str(year))}: {inline(record)}{comma}")
        lines.append("  }" + ("," if i < len(players) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def save_cluster_json(payload: Mapping, path: Path) -> Path:
    """결과를 JSON 으로 저장한다(임시 파일에 쓴 뒤 교체)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps_description(payload)
    json.loads(text)  # 형식 검증

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
    logger.info("저장: %s (선수 %s명)", path, f"{len(payload):,}")
    return path


# --------------------------------------------------------------------------- #
# 전체 파이프라인
# --------------------------------------------------------------------------- #


def run(
    k: int = DEFAULT_K,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_path: Path | None = None,
    years: Iterable[int] | None = None,
    features: Sequence[str] = DEFAULT_FEATURES,
    min_pitches: int = DEFAULT_MIN_PITCHES,
    fit_sample: int | None = DEFAULT_FIT_SAMPLE,
    chunksize: int = DEFAULT_CHUNKSIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
    model_out: Path | None = None,
    save_gmm: bool = True,
    save_json: bool = True,
    model: PitchTypeGMM | None = None,
) -> tuple[pd.DataFrame, PitchTypeGMM, pd.DataFrame]:
    """로드 → 1차 클러스터링(GMM) → 투수-시즌 집계 → JSON 저장.

    - ``model`` 을 주면 GMM 을 새로 적합하지 않고 그 모델로 할당만 한다
      (``k``, ``features``, ``fit_sample`` 은 무시되고 모델 설정을 따른다).
    - ``save_json=True`` 면 결과를 ``output_path`` (없으면
      ``processed_dir/pitcher_repertoire_clusters_k{K}.json``)에 저장한다.
    - ``save_gmm=True`` 이고 새로 적합했으면 모델을 ``model_out`` (없으면
      ``processed_dir/pitch_type_gmm_k{K}.joblib``)에 저장한다.

    Returns
    -------
    (seasons, model, pitches)
        ``seasons`` : 투수-시즌 집계표 (:func:`summarize_pitcher_seasons` 참고)
        ``model``   : 적합한 1차 클러스터링 모델
        ``pitches`` : 모든 투구 + ``cluster`` 컬럼
    """
    fitted_here = model is None
    if model is not None:
        features = model.features
        k = model.n_components

    # 1. 로드 — 모든 연도(또는 years)의 모든 투구
    files = find_movement_files(processed_dir, years)
    pitches = load_pitch_data(files, features, chunksize)

    # 2. 1차 클러스터링 — 적합은 표본(fit_sample)으로, 할당은 모든 투구에
    if model is None:
        model = fit_pitch_gmm(
            pitches,
            n_components=k,
            features=features,
            fit_sample=fit_sample,
            random_state=random_state,
        )
    else:
        logger.info("주어진 GMM 모델(K=%d)로 클러스터를 할당합니다(재적합 없음).", k)
    proba = model.predict_proba(pitches)
    labels = proba.argmax(axis=1).astype("int64")
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        logger.info(
            "1차 클러스터 요약\n%s",
            summarize_components(model, pitches, proba=proba).round(2),
        )
    del proba
    pitches["cluster"] = labels

    if save_gmm and fitted_here:
        save_model(model, model_out or default_model_path(k, processed_dir))

    # 3. 투수-시즌 집계 (최빈 클러스터 + 주 패스트볼 평균 구속)
    seasons = summarize_pitcher_seasons(pitches, labels, model.n_components)
    seasons = filter_min_pitches(seasons, min_pitches)
    logger.info(
        "최빈 클러스터 비율(cluster_share) 중앙값 %.2f — 낮을수록 여러 클러스터에 고르게 퍼진 투수",
        seasons["cluster_share"].median() if len(seasons) else float("nan"),
    )

    # 4. 저장
    if save_json:
        save_cluster_json(
            build_description_payload(seasons),
            output_path or default_output_path(k, processed_dir),
        )

    return seasons, model, pitches


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "모든 투구에 GMM 1차 클러스터링을 하고, 투수-시즌별 최빈 클러스터와 "
            "주 패스트볼 평균 구속을 {MLB ID: {연도: {average_velocity, cluster}}} JSON 으로 저장합니다."
        ),
    )
    parser.add_argument(
        "--k", type=int, default=DEFAULT_K,
        help=f"1차 클러스터(GMM 성분) 개수 K (기본값: {DEFAULT_K})",
    )
    parser.add_argument(
        "--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR,
        help=f"입력 디렉토리 (기본값: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="결과 JSON 경로 (기본값: <processed-dir>/pitcher_repertoire_clusters_k{K}.json)",
    )
    parser.add_argument(
        "--model-in", type=Path, default=None,
        help="저장된 GMM 모델을 불러와 재적합 없이 할당만 합니다 (--k 등은 무시).",
    )
    parser.add_argument(
        "--years", type=int, nargs="+", default=None,
        help="사용할 연도 (기본값: 읽을 수 있는 모든 연도)",
    )
    parser.add_argument(
        "--features", nargs="+", default=list(DEFAULT_FEATURES),
        help=f"GMM 피처 (기본값: {' '.join(DEFAULT_FEATURES)})",
    )
    parser.add_argument(
        "--min-pitches", type=int, default=DEFAULT_MIN_PITCHES,
        help=f"투수-시즌 최소 투구 수 (기본값: {DEFAULT_MIN_PITCHES})",
    )
    parser.add_argument(
        "--fit-sample", type=int, default=DEFAULT_FIT_SAMPLE,
        help=(
            f"GMM 적합에 쓸 표본 크기 (기본값: {DEFAULT_FIT_SAMPLE:,}, 0 이면 전체). "
            "클러스터 할당은 항상 모든 투구에 한다."
        ),
    )
    parser.add_argument(
        "--model-out", type=Path, default=None,
        help="GMM(+표준화기) 저장 경로 (기본값: <processed-dir>/pitch_type_gmm_k{K}.joblib)",
    )
    parser.add_argument(
        "--no-save-model", action="store_true",
        help="GMM 모델을 저장하지 않습니다.",
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

    seasons, model, _ = run(
        k=args.k,
        processed_dir=args.processed_dir,
        output_path=args.output,
        years=args.years,
        features=args.features,
        min_pitches=args.min_pitches,
        fit_sample=args.fit_sample or None,
        chunksize=args.chunksize,
        random_state=args.random_state,
        model_out=args.model_out,
        save_gmm=not args.no_save_model,
        model=load_model(args.model_in) if args.model_in else None,
    )

    print("\n===== 투수-시즌 1차 클러스터 요약 =====")
    print(f"K={model.n_components} | 투수-시즌 {len(seasons):,}개 | "
          f"투수 {seasons['pitcher'].nunique():,}명")
    print("최빈 클러스터별 투수-시즌 수:",
          seasons["cluster"].value_counts().sort_index().to_dict())
    print(f"저장: {args.output or default_output_path(model.n_components, args.processed_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
