"""
2단계: 체공시간 보정 무브먼트(ivb_ft, hb_ft) 계산
------------------------------------------------
가이드 문서(체공시간_보정_무브먼트_계산_가이드.md)의 계산식을 그대로 구현.
입력: interim/pitches_clean.pkl (1단계 산출물)
출력: interim/pitches_with_movement.pkl
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

TRAIN_YEARS = [2021, 2022, 2023]          # 기준 체공시간 학습 연도 (고정)
PITCH_TYPES = ["FF", "SI", "FC"]
PLATE_Y_FT = 17.0 / 12.0
REFERENCE_Y_FT = 50.0
MIN_FLIGHT_TIME_S = 0.25
MAX_FLIGHT_TIME_S = 0.60


def time_at_y(vy0, ay, target_y, reference_y=50.0):
    """Statcast y=50ft 기준 궤적에서 target_y 도달 시각 계산."""
    vy = np.asarray(vy0, dtype=float)
    accel = np.asarray(ay, dtype=float)
    target = np.asarray(target_y, dtype=float)
    vy, accel, target = np.broadcast_arrays(vy, accel, target)

    c = reference_y - target
    discriminant = vy**2 - 2.0 * accel * c
    result = np.full(vy.shape, np.nan, dtype=float)

    finite = (
        np.isfinite(vy) & np.isfinite(accel) & np.isfinite(target)
        & (discriminant >= 0)
    )

    linear = finite & np.isclose(accel, 0.0)
    result[linear] = np.divide(
        -c[linear], vy[linear],
        out=np.full(linear.sum(), np.nan),
        where=vy[linear] != 0,
    )

    quadratic = finite & ~linear
    sqrt_disc = np.sqrt(np.where(quadratic, discriminant, np.nan))
    root_1 = (-vy - sqrt_disc) / accel
    root_2 = (-vy + sqrt_disc) / accel
    nearest = np.where(np.abs(root_1) <= np.abs(root_2), root_1, root_2)
    result[quadratic] = nearest[quadratic]
    return result


def add_flight_time_adjusted_movement(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    # raw -> inch
    data["ivb_raw_inches"] = data["pfx_z"] * 12.0
    data["hb_raw_inches"] = data["pfx_x"] * 12.0

    # 암사이드 양수로 통일 (우투 -12, 좌투 +12)
    hand_factor = data["p_throws"].map({"R": -12.0, "L": 12.0})
    data["hb_arm_side_inches"] = data["pfx_x"] * hand_factor

    # 체공시간
    release_time = time_at_y(data["vy0"], data["ay"], data["release_pos_y"],
                              reference_y=REFERENCE_Y_FT)
    plate_time = time_at_y(data["vy0"], data["ay"], PLATE_Y_FT,
                            reference_y=REFERENCE_Y_FT)
    data["flight_time_s"] = plate_time - release_time
    invalid = ~np.isfinite(data["flight_time_s"]) | (data["flight_time_s"] <= 0)
    data.loc[invalid, "flight_time_s"] = np.nan

    # 구종별 기준 체공시간 (2021-2023 고정 학습)
    valid_ref = (
        data["game_year"].isin(TRAIN_YEARS)
        & data["p_throws"].isin(["R", "L"])
        & data["flight_time_s"].between(MIN_FLIGHT_TIME_S, MAX_FLIGHT_TIME_S)
        & data[["ivb_raw_inches", "hb_arm_side_inches", "flight_time_s"]].notna().all(axis=1)
        & data["pitch_type"].isin(PITCH_TYPES)
    )
    reference_times = (
        data.loc[valid_ref]
        .groupby("pitch_type", observed=True)["flight_time_s"]
        .median()
    )
    missing_ref = set(PITCH_TYPES).difference(reference_times.index)
    if missing_ref:
        raise ValueError(f"기준 체공시간을 계산할 수 없는 구종: {sorted(missing_ref)}")

    data["reference_flight_time_s"] = data["pitch_type"].map(reference_times)

    valid_adj = data["flight_time_s"].gt(0) & data["reference_flight_time_s"].gt(0)
    data["flight_time_scale"] = np.where(
        valid_adj,
        (data["reference_flight_time_s"] / data["flight_time_s"]) ** 2,
        np.nan,
    )
    data["ivb_ft"] = data["ivb_raw_inches"] * data["flight_time_scale"]
    data["hb_ft"] = data["hb_arm_side_inches"] * data["flight_time_scale"]

    print("[flight_time_adjust] 구종별 기준 체공시간(초):")
    print(reference_times)
    return data


if __name__ == "__main__":
    df = pd.read_pickle(INTERIM_DIR / "pitches_clean.pkl")
    df = add_flight_time_adjusted_movement(df)

    out_path = INTERIM_DIR / "pitches_with_movement.pkl"
    df.to_pickle(out_path)
    print(f"저장 완료: {out_path} ({len(df):,}행)")
