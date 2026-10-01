"""Sample real Statcast pitches for the existing React 3D viewer.

The raw monthly CSVs are scanned only on the first request for a pitcher-season.
The bounded result is cached under data/processed and never committed.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from src.visualization.dashboard_formatter import build_visualization_data


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "processed" / "trajectory_cache"
SAMPLES_PER_TYPE = 12


def sample_pitch_rows(
    files: list[Path],
    player_id: int,
    *,
    per_type: int = SAMPLES_PER_TYPE,
    season_stats: dict[str, dict[str, float | int | None]] | None = None,
) -> list[dict[str, str]]:
    """Reservoir-sample pitches and optionally collect full-season pitch counts/speeds."""
    if per_type < 1:
        raise ValueError("per_type must be positive")
    rng = random.Random(player_id)
    selected: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: dict[str, int] = defaultdict(int)
    speed_sums: dict[str, float] = defaultdict(float)
    speed_counts: dict[str, int] = defaultdict(int)
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), start=2):
                if row.get("pitcher") != str(player_id) or row.get("game_type") != "R":
                    continue
                pitch_type = (row.get("pitch_type") or "").strip()
                if not pitch_type:
                    continue
                seen[pitch_type] += 1
                try:
                    speed = float(row.get("release_speed") or "")
                except ValueError:
                    speed = float("nan")
                if math.isfinite(speed):
                    speed_sums[pitch_type] += speed
                    speed_counts[pitch_type] += 1
                row["_source_file"] = path.name
                row["_source_row"] = str(line_number)
                bucket = selected[pitch_type]
                if len(bucket) < per_type:
                    bucket.append(row)
                else:
                    index = rng.randrange(seen[pitch_type])
                    if index < per_type:
                        bucket[index] = row
    if season_stats is not None:
        season_stats.update({
            pitch_type: {
                "season_count": count,
                "average_speed_mph": (
                    round(speed_sums[pitch_type] / speed_counts[pitch_type], 1)
                    if speed_counts[pitch_type] else None
                ),
            }
            for pitch_type, count in seen.items()
        })
    return [row for bucket in selected.values() for row in bucket]


def pitcher_trajectory_data(player_id: int, year: int) -> dict:
    files = sorted((RAW_DIR / str(year)).glob(f"statcast_{year}-*.csv"))
    if not files:
        raise FileNotFoundError(f"{year} 시즌 원본 Statcast CSV가 없습니다.")
    cache_file = CACHE_DIR / f"{year}_{player_id}.json"
    newest_source = max(path.stat().st_mtime for path in files)
    if cache_file.exists() and cache_file.stat().st_mtime >= newest_source:
        with cache_file.open(encoding="utf-8") as handle:
            cached = json.load(handle)
        if all("usage_pct" in pitch_type for pitch_type in cached.get("pitch_types", [])):
            return cached

    season_stats: dict[str, dict[str, float | int | None]] = {}
    rows = sample_pitch_rows(files, player_id, season_stats=season_stats)
    if not rows:
        raise ValueError(f"{player_id}의 {year} 정규시즌 투구를 찾지 못했습니다.")
    payload = build_visualization_data(rows, samples=31)
    season_pitch_count = sum(int(stats["season_count"]) for stats in season_stats.values())
    for pitch_type in payload["pitch_types"]:
        stats = season_stats[pitch_type["code"]]
        pitch_type["season_count"] = stats["season_count"]
        pitch_type["usage_pct"] = round(100 * int(stats["season_count"]) / season_pitch_count, 1)
        pitch_type["average_speed_mph"] = stats["average_speed_mph"]
    payload["pitcher"]["id"] = str(player_id)
    payload["season"] = year
    payload["season_pitch_count"] = season_pitch_count
    payload["sampling_note"] = f"구종별 최대 {SAMPLES_PER_TYPE}개 실제 Statcast 투구를 시즌 전체에서 표본 추출"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(cache_file)
    return payload
