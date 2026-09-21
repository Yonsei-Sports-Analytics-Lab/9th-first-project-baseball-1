"""Statcast 원본 CSV 불러오기와 품질 필터(결측 투구 제거)."""
from pathlib import Path

import pandas as pd

from src.utils.config import FASTBALLS, NEEDED_COLUMNS, NUMERIC_COLUMNS, RAW_DIR


def load_statcast(raw_dir=RAW_DIR, pitch_types=FASTBALLS, columns=NEEDED_COLUMNS):
    """raw_dir/연도/statcast_*.csv 를 모두 읽어서 지정 구종만 합친다."""
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("*/statcast_*.csv"))
    if not files:
        raise FileNotFoundError(
            "data/raw/ 안에 statcast_*.csv 가 없습니다. Drive 데이터를 data/raw/연도/ 에 넣었는지 확인하세요."
        )

    frames = []
    for f in files:
        part = pd.read_csv(f, usecols=lambda c: c in columns, low_memory=False)
        frames.append(part[part["pitch_type"].isin(pitch_types)])
    data = pd.concat(frames, ignore_index=True)

    missing = set(columns) - set(data.columns)
    if missing:
        raise KeyError(f"필수 칼럼이 없습니다: {sorted(missing)}")

    for col in NUMERIC_COLUMNS:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    print(f"CSV {len(files)}개 → {'/'.join(pitch_types)} 투구 {len(data):,}개")
    return data


def clean_missing_values(data):
    """정규시즌, 피치아웃 제외, 좌/우투 확인, 필수값 결측 투구 제거.

    결측치는 채우지 않고 해당 투구를 제외한다 (0으로 채우면 의미가 달라짐).
    """
    before = len(data)
    out = data[
        (data["game_type"] == "R")
        & (data["description"] != "pitchout")
        & data["p_throws"].isin(["R", "L"])
    ].dropna(subset=["pfx_x", "pfx_z", "release_pos_y", "vy0", "ay", "arm_angle"])
    print(f"품질 필터: {before:,} → {len(out):,} 투구")
    return out.copy()
