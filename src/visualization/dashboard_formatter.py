"""``data_*.csv`` Statcast 파일을 3D 뷰어용 JSON으로 변환한다.

브라우저는 저장소의 ``data/processed`` 디렉터리를 직접 탐색할 수 없다. 이
모듈이 CSV 탐색, 투수 선택, 입력 검증과 궤적 복원을 담당하고 React 뷰어는
여기서 만든 점을 그대로 렌더링한다.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict

from src.visualization.pitch_trajectory import (
    TrajectoryError,
    reconstruct_pitch_trajectory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "src"
    / "visualization"
    / "pitch_3d"
    / "public"
    / "pitch-data.json"
)
DEFAULT_PATTERN = "data_*.csv"

PITCHER_NAME_COLUMNS = (
    "player_name",
    "pitcher_name",
    "pitcher_full_name",
    "name",
)
PITCHER_ID_COLUMNS = ("pitcher", "pitcher_id", "mlbam_id")


class PitchCsvError(ValueError):
    """CSV 탐색 또는 투수 선택에 실패했을 때 발생한다."""


class PitchTypeSummary(TypedDict):
    code: str
    name: str
    count: int
    average_speed_mph: float | None


class ViewerTrajectory(TypedDict):
    id: str
    pitch_type: str
    pitch_name: str
    release_speed: float | None
    method: str
    flight_time: float
    points: list[dict[str, float]]


def discover_pitch_csvs(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    *,
    pattern: str = DEFAULT_PATTERN,
) -> list[Path]:
    """``data/processed``에서 이름이 ``data_*.csv``인 파일을 찾는다."""

    directory = Path(data_dir).expanduser().resolve()
    if not directory.is_dir():
        raise PitchCsvError(f"데이터 디렉터리를 찾을 수 없습니다: {directory}")
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def read_pitch_csvs(paths: Iterable[str | Path]) -> list[dict[str, str]]:
    """하나 이상의 UTF-8 CSV를 읽고 각 행에 원본 파일명을 기록한다."""

    rows: list[dict[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise PitchCsvError(f"CSV 파일을 찾을 수 없습니다: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if not reader.fieldnames:
                raise PitchCsvError(f"CSV 헤더가 없습니다: {path}")
            for source_row_number, row in enumerate(reader, start=2):
                normalized = {
                    str(key).strip(): value.strip() if isinstance(value, str) else value
                    for key, value in row.items()
                    if key is not None
                }
                normalized["_source_file"] = path.name
                normalized["_source_row"] = str(source_row_number)
                rows.append(normalized)
    return rows


def available_pitchers(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """CSV에 명시된 투수 이름을 중복 없이 정렬해 반환한다."""

    return sorted(
        {
            name
            for row in rows
            if (name := _first_text(row, PITCHER_NAME_COLUMNS)) is not None
        },
        key=str.casefold,
    )


def build_visualization_data(
    rows: Sequence[Mapping[str, object]],
    *,
    pitcher: str | None = None,
    samples: int = 61,
    max_pitches: int | None = None,
) -> dict[str, Any]:
    """CSV 행을 선택한 투수의 3D 뷰어 payload로 바꾼다.

    ``pitcher``는 대소문자를 무시한 완전 일치로 찾는다. 이름 열이 없는 단일
    투수 파일도 지원하며, 이 경우 파일명의 ``data_`` 뒤 부분을 표시명으로
    사용한다. 유효하지 않은 투구 행은 전체 작업을 중단하지 않고 ``skipped``
    진단에 남긴다.
    """

    if not rows:
        raise PitchCsvError("CSV에 투구 행이 없습니다.")
    if samples < 2:
        raise PitchCsvError("samples는 2 이상이어야 합니다.")
    if max_pitches is not None and max_pitches < 1:
        raise PitchCsvError("max_pitches는 1 이상이어야 합니다.")

    names = available_pitchers(rows)
    selected_name = _resolve_pitcher_name(rows, names, pitcher)
    selected_rows = [row for row in rows if _row_matches_pitcher(row, selected_name)]
    if not selected_rows:
        choices = ", ".join(names) if names else "없음"
        raise PitchCsvError(
            f"투수 {pitcher!r}의 행을 찾을 수 없습니다. 사용 가능: {choices}"
        )

    if max_pitches is not None:
        selected_rows = _evenly_sample(selected_rows, max_pitches)

    trajectories: list[ViewerTrajectory] = []
    skipped: list[dict[str, str]] = []
    pitch_type_counts: Counter[str] = Counter()
    pitch_type_names: dict[str, str] = {}
    speeds: dict[str, list[float]] = {}

    for index, row in enumerate(selected_rows, start=1):
        pitch_type = _first_text(row, ("pitch_type",)) or "UNK"
        pitch_name = _first_text(row, ("pitch_name",)) or pitch_type
        try:
            result = reconstruct_pitch_trajectory(
                row,
                samples=samples,
                coordinate_system="threejs",
                pfx_unit="feet",
            )
        except TrajectoryError as error:
            skipped.append(
                {
                    "source_file": str(row.get("_source_file", "")),
                    "source_row": str(row.get("_source_row", index)),
                    "reason": str(error),
                }
            )
            continue

        release_speed = _number(row.get("release_speed"))
        pitch_id = _pitch_id(row, index)
        trajectories.append(
            ViewerTrajectory(
                id=pitch_id,
                pitch_type=pitch_type,
                pitch_name=pitch_name,
                release_speed=release_speed,
                method=result["method"],
                flight_time=result["flight_time"],
                points=result["points"],
            )
        )
        pitch_type_counts[pitch_type] += 1
        pitch_type_names.setdefault(pitch_type, pitch_name)
        if release_speed is not None:
            speeds.setdefault(pitch_type, []).append(release_speed)

    if not trajectories:
        first_reason = skipped[0]["reason"] if skipped else "알 수 없는 오류"
        raise PitchCsvError(
            "시각화할 수 있는 투구가 없습니다. 첫 번째 오류: " + first_reason
        )

    pitch_types: list[PitchTypeSummary] = []
    for pitch_type, count in sorted(
        pitch_type_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        type_speeds = speeds.get(pitch_type, [])
        pitch_types.append(
            PitchTypeSummary(
                code=pitch_type,
                name=pitch_type_names[pitch_type],
                count=count,
                average_speed_mph=(
                    round(sum(type_speeds) / len(type_speeds), 1)
                    if type_speeds
                    else None
                ),
            )
        )

    source_files = sorted(
        {str(row.get("_source_file", "")) for row in selected_rows}
    )
    return {
        "schema_version": 1,
        "pitcher": {
            "name": selected_name,
            "id": _first_text(selected_rows[0], PITCHER_ID_COLUMNS),
        },
        "source_files": source_files,
        "pitch_count": len(trajectories),
        "selected_row_count": len(selected_rows),
        "pitch_types": pitch_types,
        "trajectories": trajectories,
        "skipped": skipped,
    }


def write_visualization_json(payload: Mapping[str, object], output: str | Path) -> Path:
    """뷰어 payload를 UTF-8 JSON으로 저장한다."""

    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, ensure_ascii=False, separators=(",", ":"))
        json_file.write("\n")
    temporary.replace(path)
    return path


def _resolve_pitcher_name(
    rows: Sequence[Mapping[str, object]], names: Sequence[str], pitcher: str | None
) -> str:
    if pitcher is not None:
        requested = pitcher.strip()
        matches = [name for name in names if name.casefold() == requested.casefold()]
        if matches:
            return matches[0]
        if not names:
            return requested
        choices = ", ".join(names)
        raise PitchCsvError(f"투수 {pitcher!r}를 찾을 수 없습니다. 사용 가능: {choices}")
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        raise PitchCsvError(
            "CSV에 여러 투수가 있습니다. --pitcher로 선택하세요: " + ", ".join(names)
        )
    source = str(rows[0].get("_source_file", "data_unknown.csv"))
    stem = Path(source).stem
    return stem.removeprefix("data_").replace("_", " ") or "Unknown pitcher"


def _row_matches_pitcher(row: Mapping[str, object], selected_name: str) -> bool:
    row_name = _first_text(row, PITCHER_NAME_COLUMNS)
    return row_name is None or row_name.casefold() == selected_name.casefold()


def _first_text(row: Mapping[str, object], columns: Iterable[str]) -> str | None:
    for column in columns:
        value = row.get(column)
        if value is not None:
            text = str(value).strip()
            if text and text.casefold() not in {"nan", "none", "null"}:
                return text
    return None


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _pitch_id(row: Mapping[str, object], fallback_index: int) -> str:
    source = str(row.get("_source_file", "pitch"))
    parts = [
        _first_text(row, ("game_pk",)),
        _first_text(row, ("at_bat_number",)),
        _first_text(row, ("pitch_number",)),
    ]
    if any(parts):
        return source + ":" + "-".join(part or "0" for part in parts)
    return f"{source}:{row.get('_source_row', fallback_index)}"


def _evenly_sample(
    rows: Sequence[Mapping[str, object]], limit: int
) -> list[Mapping[str, object]]:
    if len(rows) <= limit:
        return list(rows)
    if limit == 1:
        return [rows[0]]
    last = len(rows) - 1
    return [rows[round(index * last / (limit - 1))] for index in range(limit)]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="data/processed/data_*.csv를 3D 투구 궤적 JSON으로 변환합니다."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="입력 CSV. 생략하면 data/processed/data_*.csv를 모두 읽습니다.",
    )
    parser.add_argument("--pitcher", help="여러 투수가 있을 때 선택할 투수 이름")
    parser.add_argument("--samples", type=int, default=61, help="궤적당 점 개수")
    parser.add_argument(
        "--max-pitches",
        type=int,
        default=300,
        help="브라우저에 보낼 최대 투구 수(기본 300)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--list-pitchers", action="store_true", help="투수 이름만 출력하고 종료"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = [path.resolve() for path in args.inputs]
    if not paths:
        paths = discover_pitch_csvs()
    if not paths:
        raise PitchCsvError(
            f"{DEFAULT_DATA_DIR}에서 {DEFAULT_PATTERN!r} 파일을 찾을 수 없습니다."
        )
    rows = read_pitch_csvs(paths)
    if args.list_pitchers:
        for name in available_pitchers(rows):
            print(name)
        return 0
    payload = build_visualization_data(
        rows,
        pitcher=args.pitcher,
        samples=args.samples,
        max_pitches=args.max_pitches,
    )
    destination = write_visualization_json(payload, args.output)
    print(
        f"{payload['pitcher']['name']}: {payload['pitch_count']}개 투구를 "
        f"{destination}에 저장했습니다."
    )
    skipped = payload["skipped"]
    if skipped:
        print(f"유효하지 않아 제외된 행: {len(skipped)}개")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PitchCsvError as error:
        raise SystemExit(f"오류: {error}") from error


__all__ = [
    "DEFAULT_DATA_DIR",
    "DEFAULT_OUTPUT",
    "DEFAULT_PATTERN",
    "PitchCsvError",
    "available_pitchers",
    "build_visualization_data",
    "discover_pitch_csvs",
    "read_pitch_csvs",
    "write_visualization_json",
]
