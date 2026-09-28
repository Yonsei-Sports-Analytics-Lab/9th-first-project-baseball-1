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
   - ``average_velocity`` : 그 투구들의 평균 구속 (``release_speed``, mph)

   를 구한다. 투구 수가 ``min_pitches`` (기본 200) 미만인 투수-시즌은 제외한다.
4. **저장** (:func:`save_cluster_json`)
   ``data/processed/data_description.json`` 과 같은 형식으로 저장한다::

       {
         "Shohei Ohtani": {
           "2023": { "average_velocity": 100.0, "cluster": 10 },
           ...
         },
         ...
       }

   - 선수명은 Statcast 의 ``"성, 이름"`` 을 ``"이름 성"`` 으로 바꾼다.
   - 서로 다른 투수가 같은 이름이면(예: Luis García 여러 명) 이름 뒤에
     ``" (pitcher_id)"`` 를 붙여 구분한다.

CLI 사용 예시
-------------
.. code-block:: bash

    # 기본값: K=10, 모든 연도
    python src/preprocessing/cluster_pitcher_repertoire.py

    # K 지정
    python src/preprocessing/cluster_pitcher_repertoire.py --k 7

    # 특정 연도만 사용 + 적합한 GMM 모델도 저장
    python src/preprocessing/cluster_pitcher_repertoire.py --k 10 \
        --years 2023 2024 2025 \
        --model-out data/processed/pitch_type_gmm.joblib
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
    fit_pitch_gmm,
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

#: 결과 JSON 경로 (형식은 data/processed/data_description.json 참고)
DEFAULT_OUTPUT_PATH = DEFAULT_PROCESSED_DIR / "pitcher_repertoire_clusters.json"

#: 평균 구속 반올림 자릿수
VELOCITY_DECIMALS = 1

DEFAULT_RANDOM_STATE = 42

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 3. 투수-시즌 집계
# --------------------------------------------------------------------------- #


def summarize_pitcher_seasons(
    pitches: pd.DataFrame,
    labels: np.ndarray,
    n_clusters: int,
) -> pd.DataFrame:
    """투구를 ``(pitcher, game_year)`` 로 묶어 최빈 1차 클러스터와 평균 구속을 구한다.

    Parameters
    ----------
    pitches:
        ``pitcher, game_year, player_name, p_throws, release_speed`` 를 가진 투구.
    labels:
        ``pitches`` 와 같은 길이의 1차 클러스터 번호 (0 ~ ``n_clusters``-1).

    Returns
    -------
    pd.DataFrame
        ``pitcher, player_name, p_throws, game_year, n_pitches, average_velocity,
        cluster, cluster_share, n_C0 ... n_C{K-1}``

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
    # 평균 구속 — 이 투수-시즌으로 묶인 투구들 기준 (구속 결측은 제외하고 평균)
    seasons["average_velocity"] = frame.groupby(keys)[VELOCITY_COLUMN].mean()
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
        "average_velocity", "cluster", "cluster_share",
        *[f"n_C{k}" for k in range(n_clusters)],
    ]
    seasons = seasons[ordered].sort_values(["player_name", "game_year"])
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
# 4. JSON 저장 (data_description.json 형식)
# --------------------------------------------------------------------------- #


def format_player_name(name: object) -> str:
    """Statcast ``"Ohtani, Shohei"`` → ``"Shohei Ohtani"``."""
    if not isinstance(name, str) or not name.strip():
        return ""
    last, sep, first = name.partition(",")
    if not sep:
        return name.strip()
    return f"{first.strip()} {last.strip()}".strip()


def assign_display_names(seasons: pd.DataFrame) -> pd.Series:
    """JSON 키로 쓸 선수명. 동명이인(다른 pitcher id)은 ``" (id)"`` 를 붙인다."""
    names = seasons["player_name"].map(format_player_name).astype(object)
    ids = seasons["pitcher"].astype("int64").astype(str)
    names = names.where(names != "", "pitcher " + ids)

    ids_per_name = seasons.groupby(names)["pitcher"].nunique()
    duplicated = ids_per_name[ids_per_name > 1].index
    if len(duplicated):
        logger.warning(
            "동명이인 %d건 — 이름 뒤에 pitcher id 를 붙입니다: %s",
            len(duplicated),
            ", ".join(sorted(duplicated)),
        )
        mask = names.isin(duplicated)
        names = names.where(~mask, names + " (" + ids + ")")
    return names


def build_description_payload(
    seasons: pd.DataFrame,
    velocity_decimals: int = VELOCITY_DECIMALS,
) -> dict[str, dict[str, dict[str, float | int | None]]]:
    """``{선수명: {연도: {"average_velocity": ..., "cluster": ...}}}`` 딕셔너리."""
    frame = seasons.assign(display_name=assign_display_names(seasons))
    frame = frame.sort_values(["display_name", "game_year"])

    payload: dict[str, dict[str, dict[str, float | int | None]]] = {}
    for row in frame.itertuples(index=False):
        velocity = row.average_velocity
        payload.setdefault(row.display_name, {})[str(int(row.game_year))] = {
            "average_velocity": (
                None if pd.isna(velocity) else round(float(velocity), velocity_decimals)
            ),
            "cluster": int(row.cluster),
        }
    return payload


def dumps_description(payload: Mapping[str, Mapping[str, Mapping]]) -> str:
    """data_description.json 과 같은 배치(시즌 레코드는 한 줄)로 직렬화한다."""
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
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
    years: Iterable[int] | None = None,
    features: Sequence[str] = DEFAULT_FEATURES,
    min_pitches: int = DEFAULT_MIN_PITCHES,
    fit_sample: int | None = DEFAULT_FIT_SAMPLE,
    chunksize: int = DEFAULT_CHUNKSIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
    model_out: Path | None = None,
) -> tuple[pd.DataFrame, PitchTypeGMM, pd.DataFrame]:
    """로드 → 1차 클러스터링(GMM) → 투수-시즌 집계 → JSON 저장.

    ``output_path=None`` 이면 저장하지 않고 결과만 반환한다(노트북에서 쓰기 좋다).

    Returns
    -------
    (seasons, model, pitches)
        ``seasons`` : 투수-시즌 집계표 (:func:`summarize_pitcher_seasons` 참고)
        ``model``   : 적합한 1차 클러스터링 모델
        ``pitches`` : 모든 투구 + ``cluster`` 컬럼
    """
    # 1. 로드 — 모든 연도(또는 years)의 모든 투구
    files = find_movement_files(processed_dir, years)
    pitches = load_pitch_data(files, features, chunksize)

    # 2. 1차 클러스터링 — 적합은 표본(fit_sample)으로, 할당은 모든 투구에
    model = fit_pitch_gmm(
        pitches,
        n_components=k,
        features=features,
        fit_sample=fit_sample,
        random_state=random_state,
    )
    proba = model.predict_proba(pitches)
    labels = proba.argmax(axis=1).astype("int64")
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        logger.info(
            "1차 클러스터 요약\n%s",
            summarize_components(model, pitches, proba=proba).round(2),
        )
    del proba
    pitches["cluster"] = labels

    if model_out is not None:
        save_model(model, model_out)

    # 3. 투수-시즌 집계 (최빈 클러스터 + 평균 구속)
    seasons = summarize_pitcher_seasons(pitches, labels, model.n_components)
    seasons = filter_min_pitches(seasons, min_pitches)
    logger.info(
        "최빈 클러스터 비율(cluster_share) 중앙값 %.2f — 낮을수록 여러 클러스터에 고르게 퍼진 투수",
        seasons["cluster_share"].median() if len(seasons) else float("nan"),
    )

    # 4. 저장
    if output_path is not None:
        save_cluster_json(build_description_payload(seasons), output_path)

    return seasons, model, pitches


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "모든 투구에 GMM 1차 클러스터링을 하고, 투수-시즌별 최빈 클러스터와 "
            "평균 구속을 {선수: {연도: {average_velocity, cluster}}} JSON 으로 저장합니다."
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
        "--output", type=Path, default=DEFAULT_OUTPUT_PATH,
        help=f"결과 JSON 경로 (기본값: {DEFAULT_OUTPUT_PATH})",
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
        help="적합한 GMM(+표준화기)을 joblib 으로 저장할 경로.",
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
    )

    print("\n===== 투수-시즌 1차 클러스터 요약 =====")
    print(f"K={model.n_components} | 투수-시즌 {len(seasons):,}개 | "
          f"투수 {seasons['pitcher'].nunique():,}명")
    print("최빈 클러스터별 투수-시즌 수:",
          seasons["cluster"].value_counts().sort_index().to_dict())
    print(f"저장: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
