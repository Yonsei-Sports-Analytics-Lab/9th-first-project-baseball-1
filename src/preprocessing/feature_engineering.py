"""체공시간 보정 무브먼트 (체공시간_보정_무브먼트_계산_가이드.md 1~9단계).

ivb_ft : 기준 체공시간으로 환산한 수직 무브먼트 (inch)
hb_ft  : 기준 체공시간으로 환산한 수평 무브먼트 (inch, 암사이드 +)
"""
import numpy as np

from src.utils.config import (
    MAX_FLIGHT_TIME_S, MIN_FLIGHT_TIME_S, PLATE_Y_FT, REFERENCE_Y_FT,
)


def time_at_y(vy0, ay, target_y, reference_y=REFERENCE_Y_FT):
    """y(t) = reference_y + vy0*t + 0.5*ay*t^2 궤적에서 target_y 도달 시각.

    두 근 중 t=0에 더 가까운 물리적 근을 고른다. 계산 불가능하면 NaN.
    """
    vy, accel, target = np.broadcast_arrays(
        np.asarray(vy0, float), np.asarray(ay, float), np.asarray(target_y, float)
    )
    c = reference_y - target
    disc = vy**2 - 2.0 * accel * c
    result = np.full(vy.shape, np.nan)

    ok = np.isfinite(vy) & np.isfinite(accel) & np.isfinite(target) & (disc >= 0)

    linear = ok & np.isclose(accel, 0.0) & (vy != 0)
    result[linear] = -c[linear] / vy[linear]

    quad = ok & ~np.isclose(accel, 0.0)
    sq = np.sqrt(np.where(quad, disc, np.nan))
    with np.errstate(divide="ignore", invalid="ignore"):
        r1 = (-vy - sq) / accel
        r2 = (-vy + sq) / accel
    nearest = np.where(np.abs(r1) <= np.abs(r2), r1, r2)
    result[quad] = nearest[quad]
    return result


def add_raw_movement(data):
    """pfx(ft) → inch 변환, 수평 무브먼트를 암사이드 + 로 통일."""
    out = data.copy()
    out["ivb_raw_inches"] = out["pfx_z"] * 12.0
    hand = out["p_throws"].map({"R": -1.0, "L": 1.0})
    out["hb_arm_side_inches"] = out["pfx_x"] * 12.0 * hand
    return out


def add_flight_time(data, min_s=MIN_FLIGHT_TIME_S, max_s=MAX_FLIGHT_TIME_S):
    """릴리스~홈플레이트 체공시간(flight_time_s) 계산, 범위 밖 투구 제외."""
    out = data.copy()
    t_release = time_at_y(out["vy0"], out["ay"], out["release_pos_y"])
    t_plate = time_at_y(out["vy0"], out["ay"], PLATE_Y_FT)
    out["flight_time_s"] = t_plate - t_release
    return out[out["flight_time_s"].between(min_s, max_s)].copy()


def compute_reference_times(data, train_years):
    """학습연도 투구에서 구종별 체공시간 중앙값(T_ref)."""
    ref = (
        data[data["game_year"].isin(train_years)]
        .groupby("pitch_type")["flight_time_s"]
        .median()
    )
    lost = set(data["pitch_type"].unique()) - set(ref.index)
    if lost:
        raise ValueError(f"기준 체공시간을 못 구한 구종: {sorted(lost)} (train_years 데이터 확인)")
    return ref


def apply_flight_time_adjustment(data, reference_times):
    """무브먼트 × (T_ref / T)^2."""
    out = data.copy()
    out["reference_flight_time_s"] = out["pitch_type"].map(reference_times)
    out["flight_time_scale"] = (out["reference_flight_time_s"] / out["flight_time_s"]) ** 2
    out["ivb_ft"] = out["ivb_raw_inches"] * out["flight_time_scale"]
    out["hb_ft"] = out["hb_arm_side_inches"] * out["flight_time_scale"]
    return out


def add_flight_adjusted_movement(data, train_years):
    """위 단계를 한 번에 실행. (보정된 data, 구종별 T_ref) 반환."""
    out = add_raw_movement(data)
    out = add_flight_time(out)
    reference_times = compute_reference_times(out, train_years)
    out = apply_flight_time_adjustment(out, reference_times)
    return out, reference_times


def movement_sanity_check(data):
    """가이드 23절 점검: 체공시간 범위 비율과 구종×손잡이별 평균."""
    share = data["flight_time_s"].between(0.35, 0.50).mean()
    print("체공시간 0.35~0.50초 비율:", round(share, 3))
    return (
        data.groupby(["pitch_type", "p_throws"])
        [["flight_time_s", "flight_time_scale", "ivb_ft", "hb_ft"]]
        .mean()
        .round(2)
    )
