"""전처리 파이프라인 — 원본 Statcast CSV 부터 투수-시즌 클러스터 JSON 까지.

단계와 산출물
-------------
============= ======================================== ================================================
단계           모듈                                      산출물 (``data/processed/``)
============= ======================================== ================================================
``extract``   ``extract_fastball``                     ``{연도}_processed.csv``
``movement``  ``compute_movement_reconciliation``      ``{연도}_movement_reconciliation.csv``
                                                       (+ ``reference_flight_times.json``)
``fit``       ``fit_pitch_gmm``                        ``pitch_type_gmm_k{K}.joblib``
``cluster``   ``cluster_pitcher_repertoire``           ``pitcher_repertoire_clusters_k{K}.json``
                                                       (``--cluster-output`` 으로 변경 가능)
============= ======================================== ================================================

- 각 단계는 **산출물이 이미 있으면 실행하지 않는다.** 연도별 산출물이 있는
  ``extract``/``movement`` 는 **없는 연도만** 처리한다.
- ``cluster`` 는 ``fit`` 이 저장한 모델을 불러와 할당만 한다(GMM 을 다시 적합하지 않음).
  그래서 ``fit`` 이 ``cluster`` 보다 먼저 실행된다.
- ``cluster`` 는 결과 JSON 이 있어도, 그 JSON 을 만든 모델과 지금 모델(K 가 다르거나
  ``fit`` 을 다시 했을 때)이 다르면 다시 만든다(``pipeline_state.json`` 에 기록).
- 상위 단계가 새로 실행됐는데 하위 산출물이 이미 있어 건너뛰면, 하위 결과가
  옛 데이터 기준일 수 있으므로 경고를 남긴다. 다시 만들려면 ``--force`` 를 쓴다.

CLI 사용 예시
-------------
.. code-block:: bash

    # 전체 파이프라인 (K=10)
    python src/preprocessing/preprocess_pipeline.py --k 10

    # 무엇이 실행될지 확인만
    python src/preprocessing/preprocess_pipeline.py --k 10 --dry-run

    # GMM 과 클러스터 결과를 강제로 다시 생성
    python src/preprocessing/preprocess_pipeline.py --k 10 --force fit cluster

    # 클러스터 JSON 파일명 지정
    python src/preprocessing/preprocess_pipeline.py --k 6 --cluster-output pitcher_clustered.json

    # 특정 연도만
    python src/preprocessing/preprocess_pipeline.py --k 6 --years 2023 2024 2025
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

#: 프로젝트 루트 (src/preprocessing/<이 파일> 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.preprocessing import cluster_pitcher_repertoire as cluster_step  # noqa: E402
from src.preprocessing import compute_movement_reconciliation as movement_step  # noqa: E402
from src.preprocessing import extract_fastball as extract_step  # noqa: E402
from src.preprocessing import fit_pitch_gmm as fit_step  # noqa: E402
from src.preprocessing.load_movement_data import (  # noqa: E402
    INPUT_FILE_PATTERN as MOVEMENT_FILE_PATTERN,
)

# --------------------------------------------------------------------------- #
# 상수 정의
# --------------------------------------------------------------------------- #

DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

#: 기준 체공시간 JSON (있으면 재사용해서 연도 간 기준을 고정한다)
REFERENCE_FILE_NAME = "reference_flight_times.json"

#: ``{연도}_processed.csv`` (extract 산출물 = movement 입력)
PROCESSED_FILE_PATTERN = movement_step.INPUT_FILE_PATTERN

#: 클러스터 JSON 을 어떤 모델로 만들었는지 기록하는 파일
STATE_FILE_NAME = "pipeline_state.json"

#: 실행 순서
STAGES: tuple[str, ...] = ("extract", "movement", "fit", "cluster")

DEFAULT_K = cluster_step.DEFAULT_K

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 결과 자료구조
# --------------------------------------------------------------------------- #


@dataclass
class StageResult:
    """단계 하나의 실행 결과."""

    stage: str
    status: str  # "ran" | "skipped" | "would-run"
    outputs: list[Path] = field(default_factory=list)
    detail: str = ""

    @property
    def ran(self) -> bool:
        return self.status == "ran"

    def summary(self) -> str:
        label = {"ran": "실행", "skipped": "건너뜀", "would-run": "실행 예정"}[self.status]
        names = ", ".join(path.name for path in self.outputs[:6])
        if len(self.outputs) > 6:
            names += f" 외 {len(self.outputs) - 6}개"
        text = f"[{self.stage:<8}] {label:<6}"
        if self.detail:
            text += f" | {self.detail}"
        if names:
            text += f" | {names}"
        return text


# --------------------------------------------------------------------------- #
# 산출물 경로
# --------------------------------------------------------------------------- #


def raw_years(raw_dir: Path, years: Iterable[int] | None = None) -> list[int]:
    """``data/raw`` 에 연도 디렉토리가 있는 연도 (``years`` 로 제한 가능)."""
    available = [int(path.name) for path in extract_step.find_year_dirs(raw_dir)]
    if years is None:
        return available
    wanted = {int(year) for year in years}
    missing = wanted - set(available)
    if missing:
        logger.warning("data/raw 에 없는 연도: %s", sorted(missing))
    return [year for year in available if year in wanted]


def processed_path(processed_dir: Path, year: int) -> Path:
    return Path(processed_dir) / f"{year}_processed.csv"


def movement_path(processed_dir: Path, year: int) -> Path:
    return Path(processed_dir) / movement_step.OUTPUT_FILE_TEMPLATE.format(year=year)


def target_years(
    raw_dir: Path,
    processed_dir: Path,
    years: Iterable[int] | None,
) -> list[int]:
    """파이프라인이 다룰 연도.

    ``years`` 를 주면 그 연도, 아니면 ``data/raw`` 의 연도와 이미 만들어진
    ``{연도}_processed.csv`` / ``{연도}_movement_reconciliation.csv`` 연도의 합집합.
    (원본이 없어도 중간 산출물이 있으면 이어서 진행할 수 있도록)
    """
    if years is not None:
        return sorted({int(year) for year in years})

    found: set[int] = set()
    if Path(raw_dir).is_dir():
        found.update(int(path.name) for path in extract_step.find_year_dirs(raw_dir))
    if Path(processed_dir).is_dir():
        patterns = (PROCESSED_FILE_PATTERN, MOVEMENT_FILE_PATTERN)
        for path in Path(processed_dir).iterdir():
            for pattern in patterns:
                match = pattern.match(path.name)
                if match:
                    found.add(int(match.group("year")))
    return sorted(found)


# --------------------------------------------------------------------------- #
# 단계별 실행
# --------------------------------------------------------------------------- #


def run_extract(
    years: Sequence[int],
    raw_dir: Path,
    processed_dir: Path,
    chunksize: int,
    force: bool = False,
    dry_run: bool = False,
) -> StageResult:
    """1. 월별 원본 CSV → ``{연도}_processed.csv`` (없는 연도만)."""
    outputs = [processed_path(processed_dir, year) for year in years]
    todo = [year for year, path in zip(years, outputs) if force or not path.exists()]
    if not todo:
        return StageResult("extract", "skipped", outputs, "모든 연도 산출물 존재")

    available = set(raw_years(raw_dir)) if Path(raw_dir).is_dir() else set()
    no_raw = [year for year in todo if year not in available]
    if no_raw:
        raise FileNotFoundError(
            f"{no_raw} 년의 {{연도}}_processed.csv 가 없고 원본(data/raw/{{연도}})도 없습니다."
        )

    todo_paths = [processed_path(processed_dir, year) for year in todo]
    if dry_run:
        return StageResult("extract", "would-run", todo_paths, f"연도 {todo}")

    extract_step.process_all(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        years=todo,
        chunksize=chunksize,
        overwrite=True,
    )
    return StageResult("extract", "ran", todo_paths, f"연도 {todo}")


def run_movement(
    years: Sequence[int],
    processed_dir: Path,
    chunksize: int,
    force: bool = False,
    dry_run: bool = False,
) -> StageResult:
    """2. ``{연도}_processed.csv`` → ``{연도}_movement_reconciliation.csv`` (없는 연도만).

    ``reference_flight_times.json`` 이 있으면 그 기준 체공시간을 재사용한다
    (새 연도를 추가해도 기존 연도와 같은 기준으로 보정되도록). 없거나 ``force``
    이면 학습연도에서 새로 계산해 저장한다.
    """
    outputs = [movement_path(processed_dir, year) for year in years]
    todo = [year for year, path in zip(years, outputs) if force or not path.exists()]
    if not todo:
        return StageResult("movement", "skipped", outputs, "모든 연도 산출물 존재")

    reference = Path(processed_dir) / REFERENCE_FILE_NAME
    reuse_reference = reference.exists() and not force
    detail = f"연도 {todo} | 기준 체공시간 " + ("재사용" if reuse_reference else "새로 계산")
    todo_paths = [movement_path(processed_dir, year) for year in todo]
    if dry_run:
        return StageResult("movement", "would-run", todo_paths, detail)

    movement_step.run(
        processed_dir=processed_dir,
        years=todo,
        chunksize=chunksize,
        overwrite=True,
        reference_in=reference if reuse_reference else None,
        reference_out=None if reuse_reference else reference,
    )
    return StageResult("movement", "ran", todo_paths, detail)


def run_fit(
    k: int,
    years: Sequence[int] | None,
    processed_dir: Path,
    fit_sample: int | None,
    chunksize: int,
    random_state: int,
    force: bool = False,
    dry_run: bool = False,
) -> StageResult:
    """3. 무브먼트 CSV → GMM 모델 ``pitch_type_gmm_k{K}.joblib``."""
    model_path = fit_step.default_model_path(k, processed_dir)
    if model_path.exists() and not force:
        return StageResult("fit", "skipped", [model_path], "모델 존재")
    if dry_run:
        return StageResult("fit", "would-run", [model_path], f"K={k}")

    fit_step.run(
        k=k,
        processed_dir=processed_dir,
        model_out=model_path,
        years=years,
        fit_sample=fit_sample,
        chunksize=chunksize,
        random_state=random_state,
    )
    return StageResult("fit", "ran", [model_path], f"K={k}")


def model_signature(model_path: Path) -> dict[str, Any] | None:
    """결과 JSON 이 어떤 모델로 만들어졌는지 기록할 서명 (파일명 + 수정 시각)."""
    model_path = Path(model_path)
    if not model_path.exists():
        return None
    return {"model": model_path.name, "model_mtime_ns": model_path.stat().st_mtime_ns}


def load_state(processed_dir: Path) -> dict[str, Any]:
    path = Path(processed_dir) / STATE_FILE_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("%s 를 읽지 못해 무시합니다.", path)
        return {}


def save_state(processed_dir: Path, state: dict[str, Any]) -> None:
    path = Path(processed_dir) / STATE_FILE_NAME
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_cluster_output(k: int, processed_dir: Path, output: Path | str | None) -> Path:
    """클러스터 JSON 경로. 파일명만 주면 ``processed_dir`` 아래로 둔다."""
    if output is None:
        return cluster_step.default_output_path(k, processed_dir)
    output = Path(output)
    return output if output.parent != Path(".") else Path(processed_dir) / output


def run_cluster(
    k: int,
    years: Sequence[int] | None,
    processed_dir: Path,
    min_pitches: int,
    chunksize: int,
    force: bool = False,
    dry_run: bool = False,
    output: Path | str | None = None,
) -> StageResult:
    """4. 저장된 GMM 으로 할당 → 클러스터 JSON.

    결과 파일명에 K 가 없을 수 있으므로(예: ``pitcher_clustered.json``), 어떤 모델로
    만들었는지를 ``pipeline_state.json`` 에 기록해 둔다. 결과 파일이 있어도 기록된
    모델과 지금 모델(K 또는 다시 적합한 모델)이 다르면 다시 만든다.
    """
    output = resolve_cluster_output(k, processed_dir, output)
    model_path = fit_step.default_model_path(k, processed_dir)
    signature = model_signature(model_path)
    state = load_state(processed_dir)
    recorded = state.get(output.name)

    if output.exists() and not force:
        if recorded is None or recorded == signature:
            return StageResult("cluster", "skipped", [output], "결과 JSON 존재")
        if recorded.get("model") == model_path.name:
            reason = f"K={k} 모델이 다시 적합되어 결과를 다시 생성"
        else:
            reason = f"기존 결과는 {recorded.get('model')} 기준 → K={k} 모델로 다시 생성"
    else:
        reason = f"K={k}"

    if dry_run:
        return StageResult("cluster", "would-run", [output], reason)

    model = fit_step.load_model(model_path)
    cluster_step.run(
        model=model,
        processed_dir=processed_dir,
        output_path=output,
        years=years,
        min_pitches=min_pitches,
        chunksize=chunksize,
        save_gmm=False,
    )
    state[output.name] = model_signature(model_path)
    save_state(processed_dir, state)
    return StageResult("cluster", "ran", [output], reason)


# --------------------------------------------------------------------------- #
# 전체 실행
# --------------------------------------------------------------------------- #


def run_pipeline(
    k: int = DEFAULT_K,
    years: Iterable[int] | None = None,
    raw_dir: Path = DEFAULT_RAW_DIR,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    force: Iterable[str] = (),
    dry_run: bool = False,
    fit_sample: int | None = fit_step.DEFAULT_FIT_SAMPLE,
    min_pitches: int = cluster_step.DEFAULT_MIN_PITCHES,
    chunksize: int = extract_step.DEFAULT_CHUNKSIZE,
    random_state: int = fit_step.DEFAULT_RANDOM_STATE,
    cluster_output: Path | str | None = None,
) -> list[StageResult]:
    """``extract → movement → fit → cluster`` 순서로 실행한다.

    ``cluster_output`` 으로 클러스터 JSON 경로(또는 파일명)를 바꿀 수 있다.
    기본값은 ``pitcher_repertoire_clusters_k{K}.json``.
    """
    force = set(force)
    unknown = force - set(STAGES)
    if unknown:
        raise ValueError(f"알 수 없는 단계: {sorted(unknown)} (가능: {list(STAGES)})")

    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    selected = list(years) if years is not None else None
    all_years = target_years(raw_dir, processed_dir, selected)
    if not all_years:
        raise FileNotFoundError(
            f"처리할 연도가 없습니다. {raw_dir} 에 연도 폴더(예: 2024/)를 넣어 주세요."
        )
    logger.info("대상 연도: %s | K=%d%s", all_years, k, " | dry-run" if dry_run else "")

    results: list[StageResult] = []

    def record(result: StageResult) -> None:
        results.append(result)
        upstream_ran = any(r.status in ("ran", "would-run") for r in results[:-1])
        if result.status == "skipped" and upstream_ran:
            logger.warning(
                "[%s] 상위 단계가 새로 실행됐지만 산출물이 있어 건너뜁니다. "
                "새 데이터를 반영하려면 --force %s",
                result.stage,
                " ".join(STAGES[STAGES.index(result.stage):]),
            )
        logger.info(result.summary())

    record(run_extract(all_years, raw_dir, processed_dir, chunksize,
                       "extract" in force, dry_run))
    record(run_movement(all_years, processed_dir, chunksize,
                        "movement" in force, dry_run))
    record(run_fit(k, selected, processed_dir, fit_sample, chunksize, random_state,
                   "fit" in force, dry_run))
    record(run_cluster(k, selected, processed_dir, min_pitches, chunksize,
                       "cluster" in force, dry_run, cluster_output))
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "extract_fastball → compute_movement_reconciliation → fit_pitch_gmm → "
            "cluster_pitcher_repertoire 를 순서대로 실행합니다. "
            "산출물이 이미 있는 단계는 건너뜁니다."
        ),
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K,
                        help=f"1차 클러스터(GMM 성분) 개수 K (기본값: {DEFAULT_K})")
    parser.add_argument("--years", type=int, nargs="+", default=None,
                        help="처리할 연도 (기본값: data/raw 와 data/processed 의 모든 연도)")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR,
                        help=f"원본 데이터 루트 (기본값: {DEFAULT_RAW_DIR})")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR,
                        help=f"산출물 디렉토리 (기본값: {DEFAULT_PROCESSED_DIR})")
    parser.add_argument(
        "--force", nargs="+", choices=STAGES, default=[], metavar="STAGE",
        help=f"산출물이 있어도 다시 실행할 단계 ({', '.join(STAGES)})",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="실제로 실행하지 않고 어떤 단계가 실행될지만 출력합니다.")
    parser.add_argument(
        "--fit-sample", type=int, default=fit_step.DEFAULT_FIT_SAMPLE,
        help=f"GMM 적합 표본 크기 (기본값: {fit_step.DEFAULT_FIT_SAMPLE:,}, 0 이면 전체)",
    )
    parser.add_argument(
        "--cluster-output", default=None,
        help=(
            "클러스터 JSON 경로 또는 파일명 (파일명만 주면 --processed-dir 아래). "
            "기본값: pitcher_repertoire_clusters_k{K}.json"
        ),
    )
    parser.add_argument(
        "--min-pitches", type=int, default=cluster_step.DEFAULT_MIN_PITCHES,
        help=f"투수-시즌 최소 투구 수 (기본값: {cluster_step.DEFAULT_MIN_PITCHES})",
    )
    parser.add_argument(
        "--chunksize", type=int, default=extract_step.DEFAULT_CHUNKSIZE,
        help=f"한 번에 읽을 행 수 (기본값: {extract_step.DEFAULT_CHUNKSIZE:,})",
    )
    parser.add_argument("--random-state", type=int, default=fit_step.DEFAULT_RANDOM_STATE,
                        help=f"난수 시드 (기본값: {fit_step.DEFAULT_RANDOM_STATE})")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    results = run_pipeline(
        k=args.k,
        years=args.years,
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        force=args.force,
        dry_run=args.dry_run,
        fit_sample=args.fit_sample or None,
        min_pitches=args.min_pitches,
        cluster_output=args.cluster_output,
        chunksize=args.chunksize,
        random_state=args.random_state,
    )

    print("\n===== 전처리 파이프라인 요약 =====")
    for result in results:
        print(result.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
