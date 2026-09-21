"""
1단계: raw Statcast CSV 로드 -> 전처리 -> 결측치 점검
------------------------------------------------------
입력: data/raw/ 아래 (연도별 하위 폴더 포함, 몇 단계든) Baseball Savant pitch-level CSV
출력: interim/pitches_clean.pkl  (다음 단계에서 계속 사용)
"""

from pathlib import Path

import numpy as np
import pandas as pd

# -----------------------------
# 사용자 설정 (레포 구조: data/raw, data/processed, src)
# -----------------------------
def _find_repo_root() -> Path:
    폴더 깊이가 바뀌어도 레포 루트를 자동으로 찾는다.
    ".git" 폴더나 "data" 폴더가 있는 위치를 레포 루트로 판단한다."""
    try:
        start = Path(__file__).resolve().parent
    except NameError:
        start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "data").is_dir():
            return candidate
    return start  # 표식을 못 찾으면 시작 위치 그대로 사용


ROOT = _find_repo_root()      # 레포 루트 (data/, src/, notebooks/의 공통 상위 폴더)
RAW_DIR = ROOT / "data" / "raw"                 # statcast_2021.csv 등을 여기 넣기
INTERIM_DIR = ROOT / "data" / "processed" / "interim"
INTERIM_DIR.mkdir(exist_ok=True, parents=True)

PITCH_TYPES = ["FF", "SI", "FC"]      # 주 패스트볼 후보 계열
TARGET_YEARS = [2021, 2022, 2023, 2024, 2025]

REQUIRED_COLUMNS = {
    "pitcher", "player_name", "game_year", "game_type",
    "pitch_type", "description",
    "release_speed", "release_pos_x", "release_pos_y", "release_pos_z",
    "release_extension", "release_spin_rate", "spin_axis", "arm_angle",
    "pfx_x", "pfx_z", "p_throws", "stand",
    "vx0", "vy0", "vz0", "ax", "ay", "az",
    "plate_x", "plate_z",
}


def load_raw(raw_dir: Path) -> pd.DataFrame:
    # data/raw/2021/statcast_2021-06.csv 처럼 연도별 하위 폴더에 있어도
    # 전부 찾도록 재귀 탐색(rglob) 사용.
    all_files = sorted(raw_dir.rglob("*.csv"))

    # Numbers/Excel 임시 잠금 파일("~$"로 시작) 등 데이터가 아닌 파일 제외
    files = [f for f in all_files if not f.name.startswith(("~$", "."))
              and "~$" not in f.name]
    skipped = sorted(set(all_files) - set(files))

    if not files:
        raise FileNotFoundError(
            f"{raw_dir} 안에 csv가 없습니다. Baseball Savant에서 내려받은 "
            "pitch-level CSV를 이 폴더(하위 폴더 포함)에 넣어주세요."
        )
    if skipped:
        print(f"[load_raw] 임시/잠금 파일로 판단되어 건너뜀: {[f.name for f in skipped]}")

    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, low_memory=False))
        except Exception as e:
            print(f"[load_raw] 읽기 실패, 건너뜀: {f} ({e})")
    data = pd.concat(frames, ignore_index=True)
    print(f"[load_raw] 파일 {len(frames)}개, 총 {len(data):,}행 로드")
    return data


def basic_preprocess(data: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        raise KeyError(f"필수 칼럼이 없습니다: {sorted(missing)}")

    # 숫자형 강제 변환 (문자로 섞여 들어온 값은 NaN 처리)
    numeric_cols = [
        "game_year", "release_speed", "release_pos_x", "release_pos_y",
        "release_pos_z", "release_extension", "release_spin_rate",
        "spin_axis", "arm_angle", "pfx_x", "pfx_z",
        "vx0", "vy0", "vz0", "ax", "ay", "az", "plate_x", "plate_z",
    ]
    for col in numeric_cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    before = len(data)

    # 정규시즌만, 대상 연도만, pitchout 제외
    data = data[data["game_type"] == "R"]
    data = data[data["game_year"].isin(TARGET_YEARS)]
    data = data[data["description"] != "pitchout"]

    # 좌/우 표기 정상값만
    data = data[data["p_throws"].isin(["R", "L"])]

    # 연구 대상 구종만 남김 (변화구는 이후 단계에서 다시 불러올 수 있으니
    # 지금은 FF/SI/FC 포함 여부만 표시하고, 실제 필터링은 주 패스트볼
    # 식별 단계에서 한다 -> 여기서는 전체 구종을 유지)
    data["is_fastball_candidate"] = data["pitch_type"].isin(PITCH_TYPES)

    after = len(data)
    print(f"[basic_preprocess] {before:,} -> {after:,}행 (정규시즌/연도/좌우표기 필터 후)")
    return data


def missing_value_report(data: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    report = (
        data[columns]
        .isna()
        .mean()
        .sort_values(ascending=False)
        .to_frame("missing_rate")
    )
    report["missing_rate_pct"] = (report["missing_rate"] * 100).round(2)
    return report


if __name__ == "__main__":
    df = load_raw(RAW_DIR)
    df = basic_preprocess(df)

    check_cols = [
        "release_speed", "pfx_x", "pfx_z", "arm_angle",
        "release_pos_x", "release_pos_y", "release_pos_z",
        "release_extension", "vy0", "ay",
    ]
    report = missing_value_report(df, check_cols)
    print("\n[결측률 점검]")
    print(report)

    out_path = INTERIM_DIR / "pitches_clean.pkl"
    df.to_pickle(out_path)
    print(f"\n저장 완료: {out_path} ({len(df):,}행)")
