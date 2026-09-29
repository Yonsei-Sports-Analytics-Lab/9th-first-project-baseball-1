"""체공시간 보정 무브먼트(flight-time adjusted movement) 계산 모듈.

``체공시간_보정_무브먼트_계산_가이드.md`` 의 계산 절차를
``data/processed/{연도}_processed.csv`` 에 적용해
``data/processed/{연도}_movement_reconciliation.csv`` 로 저장한다.

계산 흐름
---------
1. ``(pfx_x, pfx_z)`` × 12 → inch 단위 raw 무브먼트
2. ``p_throws`` 로 수평 무브먼트를 투수 기준(암사이드 +)으로 통일
3. ``(release_pos_y, vy0, ay)`` 로 릴리스~홈플레이트 체공시간 ``T`` 계산
4. **학습연도(기본 2021~2023)** 의 유효 투구에서 구종별 기준 체공시간
   ``T_ref,g`` (중앙값) 계산
5. 보정계수 ``C = (T_ref,g / T)^2`` 를 곱해 ``ivb_ft``, ``hb_ft`` 산출

.. note::
   기준 체공시간은 **모든 연도에 동일하게 고정** 적용된다(가이드 21절).
   따라서 연도별로 파일을 따로 처리하더라도, 기준값은 학습연도 파일 전체를
   한 번 훑어서(1-pass) 먼저 구한 뒤 각 연도에 적용한다(2-pass).

추가되는 컬럼 (가이드 10절과 동일한 명칭)
------------------------------------------
============================= ====== =========================================
컬럼                           단위    의미
============================= ====== =========================================
``ivb_raw_inches``            inch   ``12 * pfx_z``
``hb_raw_inches``             inch   ``12 * pfx_x`` (포수 시점)
``hb_arm_side_inches``        inch   ``12 * s * pfx_x`` (암사이드 +)
``release_time_s``            s      릴리스 시각 ``t_R`` (보통 음수)
``plate_time_s``              s      홈플레이트 앞면 도달 시각 ``t_P``
``flight_time_s``             s      체공시간 ``T = t_P - t_R``
``reference_flight_time_s``   s      구종별 기준 체공시간 ``T_ref,g``
``flight_time_scale``         배율    보정계수 ``(T_ref / T)^2``
``ivb_ft``                    inch   보정 수직 무브먼트
``hb_ft``                     inch   보정 수평 무브먼트(암사이드 +)
============================= ====== =========================================

CLI 사용 예시
-------------
.. code-block:: bash

    # 읽을 수 있는 모든 {연도}_processed.csv 처리
    python src/preprocessing/compute_movement_reconciliation.py

    # 기준 체공시간을 JSON으로 남기기 (재현용)
    python src/preprocessing/compute_movement_reconciliation.py \
        --reference-out data/processed/reference_flight_times.json

    # 이미 구한 기준 체공시간을 그대로 재사용 (1-pass 로 끝남)
    python src/preprocessing/compute_movement_reconciliation.py \
        --reference-in data/processed/reference_flight_times.json

    # 특정 연도만 / 학습연도 변경
    python src/preprocessing/compute_movement_reconciliation.py \
        --years 2024 2025 --train-years 2021 2022 2023
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

#: 프로젝트 루트 (src/preprocessing/<이 파일> 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 입력/출력 디렉토리
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

#: 입력 파일명 패턴 (``2024_processed.csv``)
INPUT_FILE_PATTERN = re.compile(r"^(?P<year>\d{4})_processed\.csv$")

#: 출력 파일명 형식
OUTPUT_FILE_TEMPLATE = "{year}_movement_reconciliation.csv"

#: 홈플레이트 앞면의 y좌표 (ft) = 17/12
PLATE_Y_FT = 17.0 / 12.0

#: Statcast 궤적 계수의 기준 y좌표 (ft)
REFERENCE_Y_FT = 50.0

#: ft → inch 변환계수
INCHES_PER_FOOT = 12.0

#: 기준 체공시간 학습연도
DEFAULT_TRAIN_YEARS: tuple[int, ...] = (2021, 2022, 2023)

#: 대상 구종
DEFAULT_PITCH_TYPES: tuple[str, ...] = ("FF", "SI", "FC")

#: 기준 표본으로 인정할 체공시간 범위 (s)
MIN_FLIGHT_TIME_S = 0.25
MAX_FLIGHT_TIME_S = 0.60

#: 투수 손잡이별 수평 무브먼트 부호 (암사이드가 양수가 되도록)
HAND_SIGN: dict[str, float] = {"R": -1.0, "L": 1.0}

#: 계산에 반드시 필요한 입력 컬럼
REQUIRED_COLUMNS: tuple[str, ...] = (
    "pitch_type",
    "p_throws",
    "pfx_x",
    "pfx_z",
    "release_pos_y",
    "vy0",
    "ay",
    "game_year",
)

#: 수치형으로 강제 변환할 컬럼
NUMERIC_COLUMNS: tuple[str, ...] = (
    "pfx_x",
    "pfx_z",
    "release_pos_y",
    "vy0",
    "ay",
    "game_year",
)

#: 이 모듈이 새로 만들어 붙이는 컬럼 (기존 컬럼 뒤에 순서대로 추가된다)
DERIVED_COLUMNS: tuple[str, ...] = (
    "ivb_raw_inches",
    "hb_raw_inches",
    "hb_arm_side_inches",
    "release_time_s",
    "plate_time_s",
    "flight_time_s",
    "reference_flight_time_s",
    "flight_time_scale",
    "ivb_ft",
    "hb_ft",
)

#: 기본 청크 크기 (행 단위)
DEFAULT_CHUNKSIZE = 200_000

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 결과 리포트용 자료구조
# --------------------------------------------------------------------------- #


@dataclass
class YearResult:
    """연도 단위 보정 결과 요약."""

    year: int
    source_path: Path
    output_path: Path
    rows_total: int = 0
    rows_with_flight_time: int = 0
    rows_with_movement: int = 0

    def summary(self) -> str:
        total = self.rows_total or 1
        return (
            f"[{self.year}] {self.rows_total:,}행 | "
            f"체공시간 산출 {self.rows_with_flight_time:,}행 "
            f"({self.rows_with_flight_time / total:.2%}) | "
            f"보정 무브먼트 산출 {self.rows_with_movement:,}행 "
            f"({self.rows_with_movement / total:.2%}) | "
            f"저장: {self.output_path.name}"
        )


@dataclass
class ReferenceStats:
    """기준 체공시간 계산 결과."""

    train_years: tuple[int, ...]
    reference_times: dict[str, float] = field(default_factory=dict)
    sample_sizes: dict[str, int] = field(default_factory=dict)
    source_files: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"기준 체공시간 (학습연도 {list(self.train_years)})"]
        for pitch_type in sorted(self.reference_times):
            lines.append(
                f"  {pitch_type}: {self.reference_times[pitch_type]:.6f}s "
                f"(표본 {self.sample_sizes.get(pitch_type, 0):,}개)"
            )
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "train_years": list(self.train_years),
            "min_flight_time_s": MIN_FLIGHT_TIME_S,
            "max_flight_time_s": MAX_FLIGHT_TIME_S,
            "reference_times": self.reference_times,
            "sample_sizes": self.sample_sizes,
            "source_files": [path.name for path in self.source_files],
        }


# --------------------------------------------------------------------------- #
# 파일 탐색
# --------------------------------------------------------------------------- #


def find_processed_files(
    processed_dir: Path,
    years: Iterable[int] | None = None,
) -> dict[int, Path]:
    """``{연도}_processed.csv`` 를 찾아 ``{연도: 경로}`` 로 반환한다."""
    if not processed_dir.is_dir():
        raise FileNotFoundError(f"입력 디렉토리를 찾을 수 없습니다: {processed_dir}")

    found: dict[int, Path] = {}
    for path in sorted(processed_dir.iterdir()):
        if not path.is_file():
            continue
        match = INPUT_FILE_PATTERN.match(path.name)
        if match is None:
            continue
        found[int(match.group("year"))] = path

    if years is not None:
        wanted = {int(year) for year in years}
        missing = wanted - found.keys()
        if missing:
            logger.warning("해당 연도의 입력 파일이 없습니다: %s", sorted(missing))
        found = {year: path for year, path in found.items() if year in wanted}

    return dict(sorted(found.items()))


# --------------------------------------------------------------------------- #
# 체공시간 계산 (가이드 5~6단계)
# --------------------------------------------------------------------------- #


def time_at_y(
    vy0,
    ay,
    target_y,
    reference_y: float = REFERENCE_Y_FT,
) -> np.ndarray:
    """Statcast y=50ft 기준 궤적에서 ``target_y`` 도달 시각을 계산한다.

    ``y(t) = 50 + vy0*t + 0.5*ay*t^2`` 의 두 근 중 ``t=0`` 에 더 가까운
    물리적 근을 선택한다. 판별식이 음수이면 NaN을 반환한다.
    ``ay`` 가 사실상 0이면 등속 직선운동식을 사용한다.
    """
    vy = np.asarray(vy0, dtype=float)
    accel = np.asarray(ay, dtype=float)
    target = np.asarray(target_y, dtype=float)
    vy, accel, target = np.broadcast_arrays(vy, accel, target)

    c = reference_y - target
    discriminant = vy**2 - 2.0 * accel * c
    result = np.full(vy.shape, np.nan, dtype=float)

    finite = (
        np.isfinite(vy)
        & np.isfinite(accel)
        & np.isfinite(target)
        & np.isfinite(discriminant)
        & (discriminant >= 0)
    )

    # ay 가 사실상 0이면 직선운동식
    linear = finite & np.isclose(accel, 0.0)
    if linear.any():
        result[linear] = np.divide(
            -c[linear],
            vy[linear],
            out=np.full(int(linear.sum()), np.nan),
            where=vy[linear] != 0,
        )

    # 일반적인 이차방정식
    quadratic = finite & ~linear
    if quadratic.any():
        with np.errstate(divide="ignore", invalid="ignore"):
            sqrt_discriminant = np.sqrt(np.where(quadratic, discriminant, np.nan))
            root_1 = (-vy - sqrt_discriminant) / accel
            root_2 = (-vy + sqrt_discriminant) / accel
        # y=50ft 의 t=0 에 가까운 물리적 근 선택
        nearest_root = np.where(np.abs(root_1) <= np.abs(root_2), root_1, root_2)
        result[quadratic] = nearest_root[quadratic]

    return result


# --------------------------------------------------------------------------- #
# 파생 변수 계산
# --------------------------------------------------------------------------- #


def validate_columns(columns: Sequence[str], source: Path) -> None:
    """계산에 필요한 컬럼이 모두 있는지 확인한다."""
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise KeyError(f"{source.name} 에 필수 컬럼이 없습니다: {missing}")


def coerce_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    """계산용 컬럼을 수치형으로 변환한다(변환 실패 값은 NaN)."""
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def add_raw_movement(frame: pd.DataFrame) -> pd.DataFrame:
    """가이드 3~4단계: inch 변환 및 암사이드 기준 수평 무브먼트."""
    frame["ivb_raw_inches"] = frame["pfx_z"] * INCHES_PER_FOOT
    frame["hb_raw_inches"] = frame["pfx_x"] * INCHES_PER_FOOT

    hand_sign = (
        frame["p_throws"].astype("string").str.strip().str.upper().map(HAND_SIGN)
    )
    frame["hb_arm_side_inches"] = (
        frame["pfx_x"] * INCHES_PER_FOOT * pd.to_numeric(hand_sign, errors="coerce")
    )
    return frame


def add_flight_time(frame: pd.DataFrame) -> pd.DataFrame:
    """가이드 5~6단계: 릴리스/플레이트 도달 시각과 체공시간."""
    frame["release_time_s"] = time_at_y(
        frame["vy0"], frame["ay"], frame["release_pos_y"]
    )
    frame["plate_time_s"] = time_at_y(frame["vy0"], frame["ay"], PLATE_Y_FT)

    flight_time = frame["plate_time_s"] - frame["release_time_s"]
    # 비물리적인 값(음수·0·무한대)은 잘못된 추적값으로 보고 결측 처리
    frame["flight_time_s"] = flight_time.where(
        np.isfinite(flight_time) & (flight_time > 0)
    )
    return frame


def prepare_frame(frame: pd.DataFrame, source: Path) -> pd.DataFrame:
    """한 청크에 대해 raw 무브먼트와 체공시간까지 계산한다."""
    validate_columns(frame.columns, source)
    frame = coerce_numeric(frame)
    frame = add_raw_movement(frame)
    frame = add_flight_time(frame)
    return frame


def reference_sample_mask(
    frame: pd.DataFrame,
    train_years: Sequence[int],
    pitch_types: Sequence[str],
) -> pd.Series:
    """기준 체공시간 표본(가이드 7단계의 :math:`\\mathcal{E}`) 마스크."""
    return (
        frame["game_year"].isin(list(train_years))
        & frame["pitch_type"].isin(list(pitch_types))
        & frame["p_throws"].isin(list(HAND_SIGN))
        & frame["flight_time_s"].between(MIN_FLIGHT_TIME_S, MAX_FLIGHT_TIME_S)
        & frame[["ivb_raw_inches", "hb_arm_side_inches", "flight_time_s"]]
        .notna()
        .all(axis=1)
    )


def apply_adjustment(
    frame: pd.DataFrame,
    reference_times: Mapping[str, float],
) -> pd.DataFrame:
    """가이드 8~9단계: 보정계수와 최종 보정 무브먼트."""
    frame["reference_flight_time_s"] = pd.to_numeric(
        frame["pitch_type"].map(dict(reference_times)), errors="coerce"
    )

    usable = frame["flight_time_s"].gt(0) & frame["reference_flight_time_s"].gt(0)
    scale = (frame["reference_flight_time_s"] / frame["flight_time_s"]) ** 2
    frame["flight_time_scale"] = scale.where(usable)

    frame["ivb_ft"] = frame["ivb_raw_inches"] * frame["flight_time_scale"]
    frame["hb_ft"] = frame["hb_arm_side_inches"] * frame["flight_time_scale"]
    return frame


# --------------------------------------------------------------------------- #
# 1-pass: 기준 체공시간 계산
# --------------------------------------------------------------------------- #


def iter_chunks(csv_path: Path, chunksize: int) -> Iterator[pd.DataFrame]:
    """CSV를 청크 단위로 읽어 파생 변수까지 계산한 프레임을 내보낸다."""
    reader = pd.read_csv(csv_path, chunksize=chunksize, low_memory=False)
    for chunk in reader:
        yield prepare_frame(chunk, csv_path)


def compute_reference_times(
    files: Mapping[int, Path],
    train_years: Sequence[int] = DEFAULT_TRAIN_YEARS,
    pitch_types: Sequence[str] = DEFAULT_PITCH_TYPES,
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> ReferenceStats:
    """학습연도 파일들에서 구종별 기준 체공시간(중앙값)을 계산한다.

    중앙값은 스트리밍으로 구할 수 없으므로 학습연도의 유효한 체공시간 값만
    구종별로 모아 둔 뒤 한 번에 계산한다(값 하나당 8바이트 수준).
    """
    train_set = {int(year) for year in train_years}
    train_files = {
        year: path for year, path in files.items() if int(year) in train_set
    }

    if not train_files:
        raise ValueError(
            "기준 체공시간을 계산할 학습연도 파일이 없습니다. "
            f"학습연도={sorted(train_set)}, 가용연도={sorted(files)}. "
            "--train-years 를 조정하거나 --reference-in 으로 기준값을 지정하세요."
        )

    buckets: dict[str, list[np.ndarray]] = {
        pitch_type: [] for pitch_type in pitch_types
    }

    for year, path in sorted(train_files.items()):
        logger.info("[기준값] 읽는 중: %s", path.name)
        for chunk in iter_chunks(path, chunksize):
            eligible = chunk.loc[
                reference_sample_mask(chunk, sorted(train_set), pitch_types)
            ]
            if eligible.empty:
                continue
            for pitch_type, group in eligible.groupby("pitch_type", observed=True):
                if pitch_type in buckets:
                    buckets[pitch_type].append(
                        group["flight_time_s"].to_numpy(dtype=float)
                    )

    stats = ReferenceStats(
        train_years=tuple(sorted(train_set)),
        source_files=[train_files[year] for year in sorted(train_files)],
    )

    missing: list[str] = []
    for pitch_type in pitch_types:
        parts = buckets[pitch_type]
        if not parts:
            missing.append(pitch_type)
            continue
        values = np.concatenate(parts)
        stats.reference_times[pitch_type] = float(np.median(values))
        stats.sample_sizes[pitch_type] = int(values.size)

    if missing:
        raise ValueError(
            f"기준 체공시간을 계산할 수 없는 구종: {sorted(missing)}. "
            "학습연도와 표본을 확인하세요."
        )

    return stats


def load_reference_times(path: Path) -> ReferenceStats:
    """JSON으로 저장해 둔 기준 체공시간을 불러온다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    reference_times = {
        str(key): float(value)
        for key, value in payload["reference_times"].items()
    }
    return ReferenceStats(
        train_years=tuple(int(year) for year in payload.get("train_years", ())),
        reference_times=reference_times,
        sample_sizes={
            str(key): int(value)
            for key, value in payload.get("sample_sizes", {}).items()
        },
    )


def save_reference_times(stats: ReferenceStats, path: Path) -> None:
    """기준 체공시간을 JSON으로 저장한다(재현·재사용용)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(stats.to_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("기준 체공시간 저장: %s", path)


# --------------------------------------------------------------------------- #
# 2-pass: 연도별 보정 무브먼트 산출
# --------------------------------------------------------------------------- #


def process_year_file(
    year: int,
    source_path: Path,
    output_dir: Path,
    reference_times: Mapping[str, float],
    chunksize: int = DEFAULT_CHUNKSIZE,
    overwrite: bool = True,
) -> YearResult | None:
    """한 연도 파일에 보정 무브먼트를 계산해 저장한다."""
    output_path = output_dir / OUTPUT_FILE_TEMPLATE.format(year=year)

    if output_path.exists() and not overwrite:
        logger.info("이미 존재하여 건너뜁니다(--overwrite 로 덮어쓰기): %s", output_path)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    result = YearResult(year=year, source_path=source_path, output_path=output_path)

    reference_columns: list[str] | None = None
    temp_path = output_path.with_suffix(".csv.tmp")
    if temp_path.exists():
        temp_path.unlink()
    header_written = False

    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as out_file:
            logger.info("[%s] 읽는 중: %s", year, source_path.name)
            for chunk in iter_chunks(source_path, chunksize):
                chunk = apply_adjustment(chunk, reference_times)

                if reference_columns is None:
                    reference_columns = list(chunk.columns)
                elif list(chunk.columns) != reference_columns:
                    chunk = chunk.reindex(columns=reference_columns)

                result.rows_total += len(chunk)
                result.rows_with_flight_time += int(chunk["flight_time_s"].notna().sum())
                result.rows_with_movement += int(chunk["ivb_ft"].notna().sum())

                chunk.to_csv(out_file, index=False, header=not header_written)
                header_written = True

        if not header_written:
            logger.warning("[%s] 입력에 행이 없어 저장하지 않습니다.", year)
            temp_path.unlink(missing_ok=True)
            return result

        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    logger.info(result.summary())
    return result


def run(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path | None = None,
    years: Iterable[int] | None = None,
    train_years: Sequence[int] = DEFAULT_TRAIN_YEARS,
    pitch_types: Sequence[str] = DEFAULT_PITCH_TYPES,
    chunksize: int = DEFAULT_CHUNKSIZE,
    overwrite: bool = True,
    reference_in: Path | None = None,
    reference_out: Path | None = None,
) -> tuple[ReferenceStats, list[YearResult]]:
    """전체 파이프라인 실행: 기준값 계산 → 연도별 보정 무브먼트 저장."""
    output_dir = output_dir or processed_dir

    # 기준값은 학습연도 전체에서 구해야 하므로, --years 와 무관하게 먼저 탐색한다.
    all_files = find_processed_files(processed_dir)
    if not all_files:
        raise FileNotFoundError(
            f"{processed_dir} 에 '{{연도}}_processed.csv' 파일이 없습니다. "
            "먼저 extract_fastball.py 를 실행하세요."
        )
    logger.info("입력 파일 %d개 발견: %s", len(all_files), sorted(all_files))

    if reference_in is not None:
        stats = load_reference_times(reference_in)
        logger.info("기준 체공시간을 불러왔습니다: %s", reference_in)
    else:
        stats = compute_reference_times(
            files=all_files,
            train_years=train_years,
            pitch_types=pitch_types,
            chunksize=chunksize,
        )

    logger.info("\n%s", stats.summary())

    if reference_out is not None:
        save_reference_times(stats, reference_out)

    target_files = (
        all_files
        if years is None
        else find_processed_files(processed_dir, years=years)
    )

    results: list[YearResult] = []
    for year, path in target_files.items():
        result = process_year_file(
            year=year,
            source_path=path,
            output_dir=output_dir,
            reference_times=stats.reference_times,
            chunksize=chunksize,
            overwrite=overwrite,
        )
        if result is not None:
            results.append(result)

    return stats, results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "{연도}_processed.csv 에 체공시간 보정 무브먼트를 계산해 "
            "{연도}_movement_reconciliation.csv 로 저장합니다."
        ),
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"입력 디렉토리 (기본값: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="출력 디렉토리 (기본값: --processed-dir 과 동일)",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=None,
        help="출력할 연도 (기본값: 읽을 수 있는 모든 연도)",
    )
    parser.add_argument(
        "--train-years",
        type=int,
        nargs="+",
        default=list(DEFAULT_TRAIN_YEARS),
        help=(
            "기준 체공시간 학습연도 "
            f"(기본값: {' '.join(map(str, DEFAULT_TRAIN_YEARS))})"
        ),
    )
    parser.add_argument(
        "--pitch-types",
        nargs="+",
        default=list(DEFAULT_PITCH_TYPES),
        help=f"대상 구종 (기본값: {' '.join(DEFAULT_PITCH_TYPES)})",
    )
    parser.add_argument(
        "--reference-in",
        type=Path,
        default=None,
        help="기준 체공시간 JSON을 불러와 그대로 사용합니다(학습연도 재계산 생략).",
    )
    parser.add_argument(
        "--reference-out",
        type=Path,
        default=None,
        help="계산한 기준 체공시간을 JSON으로 저장할 경로.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"한 번에 읽을 행 수 (기본값: {DEFAULT_CHUNKSIZE:,})",
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

    stats, results = run(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        years=args.years,
        train_years=args.train_years,
        pitch_types=args.pitch_types,
        chunksize=args.chunksize,
        overwrite=not args.no_overwrite,
        reference_in=args.reference_in,
        reference_out=args.reference_out,
    )

    if not results:
        logger.warning("생성된 결과 파일이 없습니다.")
        return 1

    print("\n===== 보정 무브먼트 요약 =====")
    print(stats.summary())
    for result in results:
        print(result.summary())

    return 0


if __name__ == "__main__":
    sys.exit(main())
