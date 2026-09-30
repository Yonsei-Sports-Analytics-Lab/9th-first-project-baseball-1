"""체공시간 보정 무브먼트 데이터 로드 모듈.

``compute_movement_reconciliation.py`` 가 만든
``data/processed/{연도}_movement_reconciliation.csv`` 를 찾아서,
1차 클러스터링(GMM)과 투수-시즌 집계에 필요한 컬럼만 청크 단위로 읽는다.

연도당 파일이 200~330MB 이므로 전체 컬럼을 메모리에 올리지 않는다.

주요 함수
---------
- :func:`find_movement_files` : ``{연도: 경로}`` 탐색
- :func:`iter_movement_chunks` : 필요한 컬럼만 청크로 읽고, 피처 결측 행 제거
- :func:`load_pitch_data` : 여러 연도의 투구를 하나의 DataFrame 으로
- :func:`sample_rows` : 재현 가능한 무작위 표본 추출

사용 예시
---------
.. code-block:: python

    from src.preprocessing.load_movement_data import (
        find_movement_files, load_pitch_data,
    )

    files = find_movement_files()          # 모든 연도
    pitches = load_pitch_data(files)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

import pandas as pd

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 프로젝트 루트 (src/preprocessing/<이 파일> 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 입력 디렉토리
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

#: 입력 파일명 패턴 (``2024_movement_reconciliation.csv``)
INPUT_FILE_PATTERN = re.compile(r"^(?P<year>\d{4})_movement_reconciliation\.csv$")

#: 1단계 GMM(새 구종 정의)에 쓰는 기본 피처
DEFAULT_FEATURES: tuple[str, ...] = ("ivb_ft", "hb_ft", "arm_angle")

#: 투수·시즌 식별 및 해석용 컬럼
ID_COLUMNS: tuple[str, ...] = (
    "game_year",
    "pitcher",
    "player_name",
    "pitch_type",
    "p_throws",
)

#: 구속 컬럼 (투수-시즌 평균 구속 계산용)
VELOCITY_COLUMN = "release_speed"

#: 메모리를 아끼기 위해 category 로 바꿀 문자열 컬럼
CATEGORY_COLUMNS: tuple[str, ...] = ("player_name", "pitch_type", "p_throws")

#: 기본 청크 크기 (행 단위)
DEFAULT_CHUNKSIZE = 200_000

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 파일 탐색
# --------------------------------------------------------------------------- #


def find_movement_files(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    years: Iterable[int] | None = None,
) -> dict[int, Path]:
    """``{연도}_movement_reconciliation.csv`` 를 찾아 ``{연도: 경로}`` 로 반환한다.

    ``years`` 를 주면 그 연도만 남기며, 요청한 연도의 파일이 없으면 오류를 낸다.
    """
    processed_dir = Path(processed_dir)
    if not processed_dir.is_dir():
        raise FileNotFoundError(f"디렉토리를 찾을 수 없습니다: {processed_dir}")

    found: dict[int, Path] = {}
    for path in sorted(processed_dir.iterdir()):
        if not path.is_file():
            continue
        match = INPUT_FILE_PATTERN.match(path.name)
        if match is not None:
            found[int(match.group("year"))] = path

    if not found:
        raise FileNotFoundError(
            f"{processed_dir} 에 '{{연도}}_movement_reconciliation.csv' 가 없습니다. "
            "먼저 src/preprocessing/compute_movement_reconciliation.py 를 실행하세요."
        )

    if years is not None:
        wanted = {int(year) for year in years}
        missing = wanted - found.keys()
        if missing:
            raise FileNotFoundError(f"요청한 연도의 파일이 없습니다: {sorted(missing)}")
        found = {year: path for year, path in found.items() if year in wanted}

    return dict(sorted(found.items()))


def select_years(files: Mapping[int, Path], years: Iterable[int]) -> dict[int, Path]:
    """``files`` 중 ``years`` 에 해당하는 것만 남긴다."""
    wanted = {int(year) for year in years}
    return {year: path for year, path in sorted(files.items()) if year in wanted}


# --------------------------------------------------------------------------- #
# 청크 로드
# --------------------------------------------------------------------------- #


def default_columns(features: Sequence[str] = DEFAULT_FEATURES) -> list[str]:
    """식별 컬럼 + 구속 + 피처 (중복 제거, 순서 유지)."""
    return list(dict.fromkeys([*ID_COLUMNS, VELOCITY_COLUMN, *features]))


def validate_columns(path: Path, columns: Sequence[str]) -> None:
    """CSV 헤더에 필요한 컬럼이 모두 있는지 확인한다."""
    header = pd.read_csv(path, nrows=0).columns
    # utf-8-sig 로 저장된 파일은 첫 컬럼명에 BOM 이 붙어 있을 수 있다
    header = {str(column).lstrip("﻿") for column in header}
    missing = [column for column in columns if column not in header]
    if missing:
        raise KeyError(f"{Path(path).name} 에 필요한 컬럼이 없습니다: {missing}")


def iter_movement_chunks(
    path: Path,
    features: Sequence[str] = DEFAULT_FEATURES,
    chunksize: int = DEFAULT_CHUNKSIZE,
    columns: Sequence[str] | None = None,
) -> Iterator[pd.DataFrame]:
    """필요한 컬럼만 청크로 읽고, ``features`` 에 결측이 있는 행은 버린다.

    ``features`` 와 구속 컬럼은 수치형으로 강제 변환한다(실패 값은 NaN).
    """
    features = list(features)
    usecols = list(dict.fromkeys([*(columns or default_columns(features)), *features]))
    validate_columns(path, usecols)

    numeric = [column for column in [*features, VELOCITY_COLUMN] if column in usecols]
    reader = pd.read_csv(
        path,
        usecols=lambda column: str(column).lstrip("﻿") in usecols,
        chunksize=chunksize,
        low_memory=False,
        encoding="utf-8-sig",
    )
    for chunk in reader:
        for column in numeric:
            chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
        chunk = chunk.dropna(subset=features)
        if not chunk.empty:
            yield chunk


def load_pitch_data(
    files: Mapping[int, Path],
    features: Sequence[str] = DEFAULT_FEATURES,
    chunksize: int = DEFAULT_CHUNKSIZE,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """``files`` 의 모든 투구를 하나의 DataFrame 으로 합쳐 반환한다.

    - ``features`` 에 결측이 있는 행, ``pitcher``/``game_year`` 가 없는 행은 버린다.
    - 반복이 많은 문자열 컬럼(``player_name``, ``pitch_type``, ``p_throws``)은
      ``category`` 로 바꿔 메모리를 줄인다(5개 연도 약 180만 행).
    """
    if not files:
        raise ValueError("읽을 파일이 없습니다.")

    keep = list(dict.fromkeys([*(columns or default_columns(features)), *features]))
    frames: list[pd.DataFrame] = []
    for year, path in sorted(files.items()):
        rows = 0
        for chunk in iter_movement_chunks(path, features, chunksize, columns=keep):
            frames.append(chunk[keep])
            rows += len(chunk)
        logger.info("[로드] %s: %s행", path.name, f"{rows:,}")

    if not frames:
        raise ValueError("유효한 투구를 하나도 읽지 못했습니다.")

    data = pd.concat(frames, ignore_index=True)
    del frames

    id_columns = [column for column in ("pitcher", "game_year") if column in data.columns]
    if id_columns:
        data = data.dropna(subset=id_columns).reset_index(drop=True)
        data = data.astype({column: "int64" for column in id_columns})
    for column in CATEGORY_COLUMNS:
        if column in data.columns:
            data[column] = data[column].astype("category")

    logger.info("연도 %s 전체 %s행", sorted(files), f"{len(data):,}")
    return data


def sample_rows(frame: pd.DataFrame, n: int | None, random_state: int = 42) -> pd.DataFrame:
    """``n`` 행을 무작위 추출한다. ``n`` 이 없거나 전체보다 크면 전체를 반환."""
    if n is None or len(frame) <= n:
        return frame.reset_index(drop=True)
    return frame.sample(n, random_state=random_state).reset_index(drop=True)
