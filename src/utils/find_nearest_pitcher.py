"""
유사 투수 매칭 모듈 (파이프라인 5번)

입력한 투수-시즌(MLBID, 연도)과 주 패스트볼의 클러스터·평균구속이 비슷하며 FIP가 더 낮은
투수 중에서 주 패스트볼의 투구 폼(릴리스 좌우·높이, 익스텐션, 팔각도)이 rank번째로 비슷한 투수-시즌을 찾아
(MLBID, 연도) 튜플로 반환한다.

사용법
------
1) 프로필 파일 생성 (데이터가 바뀔 때만 1회 실행, 프로젝트 루트에서)
    python -m src.utils.find_nearest_pitcher

2) 매칭 (백엔드에서 호출)
    from src.utils.find_nearest_pitcher import find_nearest_pitcher
    find_nearest_pitcher(543037, 2023, rank=1)   # -> (608032, 2025) 또는 None

필요 파일 (프로젝트 루트 기준)
------------------------------
- data/raw/{연도}/statcast_{연도}-{MM}.csv  : Statcast 원본 (build_profile 실행 시에만 필요)
- data/processed/pitcher_clustered.json     : {MLBID: {연도: {primary_pitch_type, average_velocity, cluster}}}
                                              ("MLBID-연도" 형태의 키도 지원)
- data/raw/fip_2021_2025.csv                : player_id, game_year, FIP, IP 컬럼
- data/processed/pitcher_profile.csv        : build_profile()이 만드는 결과 파일
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

# 프로젝트 루트 기준 상대 경로 (이 파일 위치: <root>/src/utils/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

CLUSTER_FILE = PROCESSED_DIR / "pitcher_clustered.json"   # main.py 전처리 결과 위치
FIP_FILE = RAW_DIR / "fip_2021_2025.csv"
PROFILE_FILE = PROCESSED_DIR / "pitcher_profile.csv"

# data/raw/{연도}/statcast_{연도}-{MM}.csv (엑셀 임시파일 "~$..." 등은 제외)
RAW_FILE_PATTERN = re.compile(r"^statcast_\d{4}-\d{2}\.csv$")

PROFILE_FEATURES = ["release_pos_x_arm", "release_pos_z", "release_extension", "arm_angle"]
Z_COLS = [f"{c}_z" for c in PROFILE_FEATURES]

_profile_cache = None


def _load_cluster_json(path):
    """클러스터 json을 (player_id, game_year, average_velocity, cluster) 표로 변환."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = []
    for key, value in data.items():
        if "-" in str(key):                      # {"543037-2023": {...}} 형식
            pid, year = str(key).split("-", 1)
            items = [(year, value)]
        else:                                    # {"543037": {"2023": {...}}} 형식
            pid, items = key, value.items()
        for year, info in items:
            primary_pitch_type = info.get("primary_pitch_type")
            if primary_pitch_type not in {"FF", "SI", "FC"}:
                raise ValueError(f"{path}에 주 패스트볼 구종이 없습니다. 군집 산출물을 다시 생성하세요.")
            records.append({"player_id": int(pid), "game_year": int(year),
                            "primary_pitch_type": primary_pitch_type,
                            "average_velocity": float(info["average_velocity"]),
                            "cluster": int(info["cluster"])})
    return pd.DataFrame(records)


def find_raw_files(raw_dir=RAW_DIR):
    """Statcast 월별 원본 목록. 연도 폴더(data/raw/2021/...) 안과 data/raw 바로 아래를 모두 찾는다."""
    raw_dir = Path(raw_dir)
    candidates = list(raw_dir.glob("*/statcast_*.csv")) + list(raw_dir.glob("statcast_*.csv"))
    return sorted(p for p in candidates if RAW_FILE_PATTERN.match(p.name))


def build_profile(cluster_file=CLUSTER_FILE, fip_file=FIP_FILE, save=True):
    """Statcast 원본 + 클러스터 json + FIP를 합쳐 투수-시즌 프로필 표를 만든다."""
    files = find_raw_files()
    if not files:
        raise FileNotFoundError(
            f"Statcast 원본이 없습니다: {RAW_DIR}/{{연도}}/statcast_{{연도}}-{{MM}}.csv")
    cluster = _load_cluster_json(cluster_file)
    use_cols = ["pitcher", "player_name", "game_year", "pitch_type", "p_throws", "release_pos_x",
                "release_pos_z", "release_extension", "arm_angle"]
    raw = pd.concat([pd.read_csv(f, usecols=use_cols) for f in files], ignore_index=True)

    # 군집·구속에 사용한 것과 동일한 대표 패스트볼 구종으로 투구 폼을 집계한다.
    raw = raw.merge(
        cluster[["player_id", "game_year", "primary_pitch_type"]],
        left_on=["pitcher", "game_year"], right_on=["player_id", "game_year"], how="inner",
    )
    raw = raw[raw["pitch_type"] == raw["primary_pitch_type"]]

    # release_pos_x를 암사이드 기준으로 통일 (우완은 부호 반전)
    raw["release_pos_x_arm"] = np.where(raw["p_throws"] == "L",
                                        raw["release_pos_x"], -raw["release_pos_x"])

    keys = ["pitcher", "game_year"]
    agg = raw.groupby(keys)[PROFILE_FEATURES].mean()
    agg["p_throws"] = raw.groupby(keys)["p_throws"].agg(lambda s: s.mode().iat[0])
    agg["player_name"] = raw.groupby(keys)["player_name"].first()   # 확인용
    agg = agg.reset_index().rename(columns={"pitcher": "player_id"})

    profile = cluster.merge(agg, on=["player_id", "game_year"], how="left")

    fip = pd.read_csv(fip_file)[["player_id", "game_year", "FIP", "IP"]]
    fip = fip.groupby(["player_id", "game_year"], as_index=False).first()
    profile = profile.merge(fip, on=["player_id", "game_year"], how="left")

    # 투구 폼 결측 제외 후 표준화
    profile = profile.dropna(subset=PROFILE_FEATURES).reset_index(drop=True)
    means = profile[PROFILE_FEATURES].mean()
    stds = profile[PROFILE_FEATURES].std(ddof=0)
    for c in PROFILE_FEATURES:
        profile[f"{c}_z"] = (profile[c] - means[c]) / stds[c]

    if save:
        profile.to_csv(PROFILE_FILE, index=False)
    return profile


def load_profile(path=PROFILE_FILE, reload=False):
    """프로필 파일을 한 번만 읽어서 메모리에 보관한다."""
    global _profile_cache
    if _profile_cache is None or reload:
        if not Path(path).exists():
            raise FileNotFoundError(f"{path}가 없습니다. build_profile()을 먼저 실행하세요.")
        _profile_cache = pd.read_csv(path)
    return _profile_cache


def rank_candidates(pitcher_id, year, velocity_tol=2.0, min_ip=None, profile=None):
    """
    조건을 통과한 후보 전체를 거리순 DataFrame으로 반환 (노트북 확인용).
    기준 투수가 없거나 FIP가 없으면 빈 DataFrame.
    """
    df = load_profile() if profile is None else profile
    pitcher_id, year = int(pitcher_id), int(year)

    target_rows = df[(df["player_id"] == pitcher_id) & (df["game_year"] == year)]
    if target_rows.empty or pd.isna(target_rows.iloc[0]["FIP"]):
        return df.iloc[0:0]
    target = target_rows.iloc[0]

    cand = df[
        (df["cluster"] == target["cluster"])
        & (df["average_velocity"].between(target["average_velocity"] - velocity_tol,
                                          target["average_velocity"] + velocity_tol))
        & (df["player_id"] != pitcher_id)      # 같은 선수는 연도 상관없이 제외
        & (df["FIP"] < target["FIP"])
    ].copy()
    if min_ip is not None:
        cand = cand[cand["IP"] >= min_ip]
    if cand.empty:
        return cand

    target_vec = target[Z_COLS].to_numpy(dtype=float)
    cand["distance"] = np.sqrt(((cand[Z_COLS].to_numpy(dtype=float) - target_vec) ** 2).sum(axis=1))
    return (cand.sort_values("distance")
                .drop_duplicates("player_id")  # 선수당 가장 가까운 시즌 하나만
                .reset_index(drop=True))


def find_nearest_pitcher(pitcher_id, year, rank=1, velocity_tol=2.0, min_ip=None, profile=None):
    """
    rank번째로 비슷한 투수-시즌을 (MLBID, 연도) 튜플로 반환한다.

    Parameters
    ----------
    pitcher_id   : int   비교하려는 투수의 MLBID
    year         : int   시즌
    rank         : int   몇 번째로 비슷한 투수를 반환할지 (기본 1)
    velocity_tol : float 평균구속 허용 차이 (mph)
    min_ip       : float 후보의 최소 이닝 (None이면 제한 없음)

    Returns
    -------
    tuple (MLBID, 연도) 또는 None
        None: 기준 투수-시즌 데이터 없음, FIP 없음, 조건에 맞는 후보 없음, rank 범위 초과
    """
    ranked = rank_candidates(pitcher_id, year, velocity_tol, min_ip, profile)
    rank = int(rank)
    if rank < 1 or rank > len(ranked):
        return None
    m = ranked.iloc[rank - 1]
    return (int(m["player_id"]), int(m["game_year"]))


if __name__ == "__main__":
    p = build_profile()
    print(f"프로필 저장 완료: {PROFILE_FILE} ({len(p)}행, FIP 있음 {p['FIP'].notna().sum()}행)")
