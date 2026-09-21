"""
3단계: 투수-시즌별 주 패스트볼 식별 -> 클러스터링용 피처 테이블 구축
--------------------------------------------------------------
- 주 패스트볼: 투수-시즌별 FF/SI/FC 중 구사 횟수가 가장 많은 계열 하나
- 최소 표본: 주 패스트볼 투수-시즌당 300구 이상 (연구계획서 초기 기준)
입력: interim/pitches_with_movement.pkl (2단계 산출물)
출력: interim/fastball_profile_table.pkl  (행 = 투수-시즌-주패스트볼)
"""

from pathlib import Path

import numpy as np
import pandas as pd

def _find_repo_root() -> Path:
    """.py로 실행하든 노트북 셀에 붙여넣든, 폴더 깊이가 바뀌어도 레포 루트를 찾는다."""
    try:
        start = Path(__file__).resolve().parent
    except NameError:
        start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "data").is_dir():
            return candidate
    return start


ROOT = _find_repo_root()
INTERIM_DIR = ROOT / "data" / "processed" / "interim"
PITCH_TYPES = ["FF", "SI", "FC"]
MIN_PITCHES_PER_PITCHER_SEASON = 300

# 클러스터링에 사용할 피처. 필요하면 여기서 추가/제거.
FEATURE_COLS = [
    "release_speed",
    "ivb_ft",
    "hb_ft",
    "arm_angle",
    "release_pos_x",
    "release_pos_z",
    "release_extension",
]


def identify_primary_fastball(data: pd.DataFrame) -> pd.DataFrame:
    fb = data[data["pitch_type"].isin(PITCH_TYPES)].copy()

    counts = (
        fb.groupby(["pitcher", "game_year", "pitch_type"], observed=True)
        .size()
        .rename("n_pitches")
        .reset_index()
    )
    # 투수-시즌별로 가장 많이 던진 계열 하나만 선택
    idx = counts.groupby(["pitcher", "game_year"], observed=True)["n_pitches"].idxmax()
    primary = counts.loc[idx].rename(columns={"pitch_type": "primary_fastball_type"})

    print(f"[identify_primary_fastball] 투수-시즌 {len(primary):,}개 중 주 패스트볼 식별")
    return primary  # columns: pitcher, game_year, primary_fastball_type, n_pitches


def build_profile_table(data: pd.DataFrame, primary: pd.DataFrame) -> pd.DataFrame:
    fb = data[data["pitch_type"].isin(PITCH_TYPES)].copy()

    # 주 패스트볼로 선택된 (투수,시즌,구종) 조합의 투구만 남김
    merged = fb.merge(
        primary.rename(columns={"primary_fastball_type": "pitch_type"}),
        on=["pitcher", "game_year", "pitch_type"],
        how="inner",
    )

    # 최소 표본 기준 적용
    merged = merged[merged["n_pitches"] >= MIN_PITCHES_PER_PITCHER_SEASON]

    # 결측 피처가 있는 투구는 프로필 집계에서 제외 (0으로 채우지 않음)
    merged = merged.dropna(subset=FEATURE_COLS)

    profile = (
        merged
        .groupby(["pitcher", "player_name", "game_year", "pitch_type"], observed=True)[FEATURE_COLS]
        .mean()
        .reset_index()
    )
    profile = profile.rename(columns={"pitch_type": "primary_fastball_type"})

    n_before = primary["pitcher"].nunique()
    n_after = profile["pitcher"].nunique()
    print(
        f"[build_profile_table] 투수-시즌 {len(profile):,}개 확정 "
        f"(최소 {MIN_PITCHES_PER_PITCHER_SEASON}구 기준, 결측 제외 후 / "
        f"투수 수 {n_before} -> {n_after})"
    )
    return profile


if __name__ == "__main__":
    df = pd.read_pickle(INTERIM_DIR / "pitches_with_movement.pkl")

    primary = identify_primary_fastball(df)
    profile = build_profile_table(df, primary)

    out_path = INTERIM_DIR / "fastball_profile_table.pkl"
    profile.to_pickle(out_path)
    print(f"저장 완료: {out_path}")
    print(profile.head())
