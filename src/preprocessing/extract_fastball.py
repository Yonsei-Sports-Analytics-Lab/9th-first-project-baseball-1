"""Statcast 월별 원본 CSV를 연도 단위로 병합/정제하는 전처리 모듈.

동작 요약
---------
1. ``data/raw/{연도}/statcast_{연도}-{월}.csv`` 파일들을 연도별로 모은다.
2. 패스트볼 계열 구종(:data:`FASTBALL_PITCH_TYPES` = ``FF``, ``SI``, ``FC``)의
   투구만 남긴다.
3. 투구 물리량 관련 필수 컬럼(:data:`REQUIRED_COLUMNS`)에 결측치(NaN)가 있는
   행을 제거한다.
4. 같은 연도의 월별 데이터를 하나로 합쳐
   ``data/processed/{연도}_processed.csv`` 로 저장한다.

원본 데이터가 수 GB 단위이므로 파일 전체를 메모리에 올리지 않고
``chunksize`` 단위로 읽어 정제한 뒤 결과 파일에 바로 이어 쓰는 방식을 사용한다.

CLI 사용 예시
-------------
.. code-block:: bash

    # 전체 연도 전처리
    python src/preprocessing/extract_fastball.py

    # 특정 연도만 (이미 결과 파일이 있으면 덮어쓰기)
    python src/preprocessing/extract_fastball.py --years 2024 2025 --overwrite

    # 청크 크기 조정 (메모리가 넉넉하면 크게)
    python src/preprocessing/extract_fastball.py --chunksize 500000

    # 추출할 구종 직접 지정 (기본값: FF SI FC)
    python src/preprocessing/extract_fastball.py --pitch-types FF SI FC SL
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 프로젝트 루트 (src/preprocessing/extract_fastball.py 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 원본 데이터 루트 (``data/raw/{연도}/...``)
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"

#: 전처리 결과 저장 위치
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

#: 추출 대상 구종 (패스트볼 계열)
#: ``FF`` 포심 패스트볼, ``SI`` 싱커(투심), ``FC`` 커터
FASTBALL_PITCH_TYPES: tuple[str, ...] = ("FF", "SI", "FC")

#: 구종 필터에 사용할 컬럼
PITCH_TYPE_COLUMN = "pitch_type"

#: 결측치가 하나라도 있으면 해당 행을 제거할 필수 컬럼
REQUIRED_COLUMNS: tuple[str, ...] = (
    "pitch_type",
    "pfx_x",
    "pfx_z",
    "release_pos_x",
    "release_pos_y",
    "release_pos_z",
    "vx0",
    "vy0",
    "vz0",
    "ax",
    "ay",
    "az",
    "release_speed",
    "p_throws",
    "release_extension",
    "game_year",
)

#: ``statcast_2021-03.csv`` 형태의 파일명만 허용 (엑셀 임시파일 ``~$``, ``.`` 시작 파일 등 제외)
MONTHLY_FILE_PATTERN = re.compile(r"^statcast_(?P<year>\d{4})-(?P<month>\d{2})\.csv$")

#: 연도 디렉토리명 패턴
YEAR_DIR_PATTERN = re.compile(r"^\d{4}$")

#: 기본 청크 크기 (행 단위)
DEFAULT_CHUNKSIZE = 200_000

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 결과 리포트용 자료구조
# --------------------------------------------------------------------------- #


@dataclass
class YearResult:
    """연도 단위 전처리 결과 요약."""

    year: int
    output_path: Path
    source_files: list[Path] = field(default_factory=list)
    rows_read: int = 0
    rows_fastball: int = 0
    rows_kept: int = 0

    @property
    def rows_dropped(self) -> int:
        return self.rows_read - self.rows_kept

    @property
    def drop_ratio(self) -> float:
        return self.rows_dropped / self.rows_read if self.rows_read else 0.0

    def summary(self) -> str:
        return (
            f"[{self.year}] 파일 {len(self.source_files)}개 | "
            f"원본 {self.rows_read:,}행 → 패스트볼 {self.rows_fastball:,}행 "
            f"→ 유지 {self.rows_kept:,}행 "
            f"(제거 {self.rows_dropped:,}행, {self.drop_ratio:.2%}) | "
            f"저장: {self.output_path}"
        )


# --------------------------------------------------------------------------- #
# 파일 탐색
# --------------------------------------------------------------------------- #


def find_year_dirs(raw_dir: Path) -> list[Path]:
    """``data/raw`` 아래에서 연도 디렉토리(4자리 숫자)만 찾아 정렬해 반환한다."""
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"원본 데이터 디렉토리를 찾을 수 없습니다: {raw_dir}")

    year_dirs = [
        path
        for path in raw_dir.iterdir()
        if path.is_dir() and YEAR_DIR_PATTERN.match(path.name)
    ]
    return sorted(year_dirs, key=lambda p: int(p.name))


def find_monthly_files(year_dir: Path) -> list[Path]:
    """연도 디렉토리 안의 월별 CSV를 월 순서대로 정렬해 반환한다.

    ``zNex~$harestatcast_2021-04.csv`` 같은 임시/잠금 파일은 패턴에 맞지 않아
    자동으로 제외된다.
    """
    year = year_dir.name
    matched: list[tuple[int, Path]] = []

    for path in year_dir.iterdir():
        if not path.is_file():
            continue
        match = MONTHLY_FILE_PATTERN.match(path.name)
        if match is None:
            if path.suffix.lower() == ".csv":
                logger.warning("파일명 규칙에 맞지 않아 건너뜁니다: %s", path.name)
            continue
        if match.group("year") != year:
            logger.warning(
                "디렉토리 연도(%s)와 파일명 연도(%s)가 달라 건너뜁니다: %s",
                year,
                match.group("year"),
                path.name,
            )
            continue
        matched.append((int(match.group("month")), path))

    return [path for _, path in sorted(matched, key=lambda item: item[0])]


# --------------------------------------------------------------------------- #
# 정제 로직
# --------------------------------------------------------------------------- #


def validate_columns(columns: Sequence[str], source: Path) -> None:
    """필수 컬럼이 모두 존재하는지 확인한다."""
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise KeyError(f"{source.name} 에 필수 컬럼이 없습니다: {missing}")


def filter_pitch_types(
    frame: pd.DataFrame,
    pitch_types: Sequence[str] = FASTBALL_PITCH_TYPES,
) -> pd.DataFrame:
    """지정한 구종(기본: 패스트볼 계열 ``FF``/``SI``/``FC``)의 행만 남긴다.

    ``pitch_type`` 이 비어 있는 행은 ``isin`` 결과가 False가 되므로 함께 제거된다.
    """
    return frame[frame[PITCH_TYPE_COLUMN].isin(list(pitch_types))]


def clean_missing_values(frame: pd.DataFrame) -> pd.DataFrame:
    """:data:`REQUIRED_COLUMNS` 중 하나라도 NaN인 행을 제거한다."""
    return frame.dropna(subset=list(REQUIRED_COLUMNS))


def iter_clean_chunks(
    csv_path: Path,
    chunksize: int = DEFAULT_CHUNKSIZE,
    pitch_types: Sequence[str] = FASTBALL_PITCH_TYPES,
) -> Iterator[tuple[pd.DataFrame, int, int]]:
    """CSV를 청크 단위로 읽어 정제 결과를 순차적으로 내보낸다.

    Yields
    ------
    tuple[pd.DataFrame, int, int]
        ``(정제된 청크, 원본 행 수, 구종 필터 통과 행 수)``
    """
    reader = pd.read_csv(
        csv_path,
        chunksize=chunksize,
        low_memory=False,
    )
    for chunk in reader:
        validate_columns(chunk.columns, csv_path)
        fastball = filter_pitch_types(chunk, pitch_types)
        yield clean_missing_values(fastball), len(chunk), len(fastball)


# --------------------------------------------------------------------------- #
# 연도 단위 처리
# --------------------------------------------------------------------------- #


def process_year(
    year_dir: Path,
    processed_dir: Path,
    chunksize: int = DEFAULT_CHUNKSIZE,
    overwrite: bool = True,
    pitch_types: Sequence[str] = FASTBALL_PITCH_TYPES,
) -> YearResult | None:
    """한 연도의 월별 CSV를 병합/정제해 ``{연도}_processed.csv`` 로 저장한다.

    Parameters
    ----------
    year_dir:
        ``data/raw/2024`` 처럼 월별 CSV가 들어있는 연도 디렉토리.
    processed_dir:
        결과 저장 디렉토리 (``data/processed``).
    chunksize:
        한 번에 읽어들일 행 수.
    overwrite:
        False이고 결과 파일이 이미 있으면 건너뛴다.
    pitch_types:
        남길 구종 코드. 기본값은 패스트볼 계열(``FF``, ``SI``, ``FC``).

    Returns
    -------
    YearResult | None
        처리 결과 요약. 건너뛴 경우 ``None``.
    """
    year = int(year_dir.name)
    output_path = processed_dir / f"{year}_processed.csv"

    if output_path.exists() and not overwrite:
        logger.info("이미 존재하여 건너뜁니다(--overwrite 로 덮어쓰기): %s", output_path)
        return None

    monthly_files = find_monthly_files(year_dir)
    if not monthly_files:
        logger.warning("[%s] 처리할 월별 CSV가 없습니다: %s", year, year_dir)
        return None

    processed_dir.mkdir(parents=True, exist_ok=True)

    result = YearResult(year=year, output_path=output_path, source_files=monthly_files)
    reference_columns: list[str] | None = None

    # 중간에 실패해도 기존 결과가 깨지지 않도록 임시 파일에 먼저 기록한다.
    temp_path = output_path.with_suffix(".csv.tmp")
    if temp_path.exists():
        temp_path.unlink()

    header_written = False

    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as out_file:
            for csv_path in monthly_files:
                logger.info("[%s] 읽는 중: %s", year, csv_path.name)
                file_rows_read = 0
                file_rows_fastball = 0
                file_rows_kept = 0

                for cleaned, raw_rows, fastball_rows in iter_clean_chunks(
                    csv_path, chunksize, pitch_types
                ):
                    file_rows_read += raw_rows
                    file_rows_fastball += fastball_rows

                    if reference_columns is None:
                        reference_columns = list(cleaned.columns)
                    elif list(cleaned.columns) != reference_columns:
                        # 연도/월에 따라 컬럼 순서나 구성이 다를 수 있으므로
                        # 첫 파일의 컬럼 구성에 맞춰 정렬한다(없으면 NaN).
                        cleaned = cleaned.reindex(columns=reference_columns)

                    if cleaned.empty:
                        continue

                    cleaned.to_csv(out_file, index=False, header=not header_written)
                    header_written = True
                    file_rows_kept += len(cleaned)

                logger.info(
                    "[%s] %s: %s행 → 패스트볼 %s행 → 유지 %s행",
                    year,
                    csv_path.name,
                    f"{file_rows_read:,}",
                    f"{file_rows_fastball:,}",
                    f"{file_rows_kept:,}",
                )
                result.rows_read += file_rows_read
                result.rows_fastball += file_rows_fastball
                result.rows_kept += file_rows_kept

        if not header_written:
            logger.warning("[%s] 조건을 만족하는 행이 없어 저장하지 않습니다.", year)
            temp_path.unlink(missing_ok=True)
            return result

        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    logger.info(result.summary())
    return result


def process_all(
    raw_dir: Path = DEFAULT_RAW_DIR,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    years: Iterable[int] | None = None,
    chunksize: int = DEFAULT_CHUNKSIZE,
    overwrite: bool = True,
    pitch_types: Sequence[str] = FASTBALL_PITCH_TYPES,
) -> list[YearResult]:
    """``data/raw`` 아래 모든(또는 지정한) 연도를 전처리한다."""
    year_dirs = find_year_dirs(raw_dir)

    if years:
        wanted = {int(year) for year in years}
        year_dirs = [path for path in year_dirs if int(path.name) in wanted]
        missing = wanted - {int(path.name) for path in year_dirs}
        if missing:
            logger.warning("원본 데이터에 없는 연도입니다: %s", sorted(missing))

    if not year_dirs:
        logger.warning("전처리할 연도 디렉토리가 없습니다: %s", raw_dir)
        return []

    results: list[YearResult] = []
    for year_dir in year_dirs:
        result = process_year(
            year_dir=year_dir,
            processed_dir=processed_dir,
            chunksize=chunksize,
            overwrite=overwrite,
            pitch_types=pitch_types,
        )
        if result is not None:
            results.append(result)

    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Statcast 월별 CSV를 연도 단위로 병합/정제합니다.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"원본 데이터 루트 (기본값: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"결과 저장 디렉토리 (기본값: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=None,
        help="처리할 연도 (기본값: 전체)",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"한 번에 읽을 행 수 (기본값: {DEFAULT_CHUNKSIZE:,})",
    )
    parser.add_argument(
        "--pitch-types",
        nargs="+",
        default=list(FASTBALL_PITCH_TYPES),
        help=(
            "추출할 구종 코드 "
            f"(기본값: {' '.join(FASTBALL_PITCH_TYPES)})"
        ),
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="결과 파일이 이미 있으면 건너뜁니다.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
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

    logger.info("추출 구종: %s", ", ".join(args.pitch_types))

    results = process_all(
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        years=args.years,
        chunksize=args.chunksize,
        overwrite=not args.no_overwrite,
        pitch_types=args.pitch_types,
    )

    if not results:
        logger.warning("생성된 결과 파일이 없습니다.")
        return 1

    print("\n===== 전처리 요약 =====")
    for result in results:
        print(result.summary())

    return 0


if __name__ == "__main__":
    sys.exit(main())
