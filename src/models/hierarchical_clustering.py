"""패스트볼 계층적 군집분석 (표준화 + Ward). 구종 이름표는 군집 변수에 쓰지 않는다."""
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src.utils.config import CLUSTER_FEATURES, VELOCITY_COLUMN

ID_COLUMNS = ["pitcher", "player_name", "p_throws", "game_year", "pitch_type"]


def build_cluster_points(data, unit="pitcher_season", years=None, min_pitches=50,
                         sample_size=8000, random_state=42, features=CLUSTER_FEATURES,
                         extra_means=(VELOCITY_COLUMN,)):
    """군집에 넣을 점을 만든다.

    unit="pitcher_season": 투수×시즌×구종 평균 (min_pitches 이상만)
    unit="pitch"         : 개별 투구 sample_size개 무작위 추출
    (투구 전체를 넣으면 거리 행렬이 n^2이라 메모리가 부족함)

    extra_means: 군집 변수는 아니지만 같이 평균내서 들고 갈 칼럼
                 (기본값: release_speed → JSON의 average_velocity)
    """
    pool = data if years is None else data[data["game_year"].isin(years)]
    extras = [c for c in extra_means if c in pool.columns]

    if unit == "pitcher_season":
        agg = {"n_pitches": (features[0], "size")}
        agg.update({f: (f, "mean") for f in features})
        agg.update({c: (c, "mean") for c in extras})
        points = pool.groupby(ID_COLUMNS).agg(**agg).reset_index()
        points = points[points["n_pitches"] >= min_pitches]
    elif unit == "pitch":
        points = pool.sample(n=min(sample_size, len(pool)), random_state=random_state)[
            ID_COLUMNS + features + extras
        ]
    else:
        raise ValueError('unit은 "pitcher_season" 또는 "pitch"만 가능합니다.')

    points = points.reset_index(drop=True)
    print(f"군집에 넣을 점: {len(points):,}개")
    if len(points) > 15000:
        print("⚠️ 점이 너무 많아 메모리가 부족할 수 있습니다. min_pitches를 올리거나 sample_size를 줄이세요.")
    return points


def ward_linkage(points, features=CLUSTER_FEATURES):
    """표준화 후 Ward 연결. (표준화된 X, linkage 행렬 Z) 반환."""
    X = StandardScaler().fit_transform(points[features])
    Z = linkage(X, method="ward")
    return X, Z


def silhouette_by_k(X, Z, k_range=range(2, 11)):
    """k별 실루엣 점수 (높을수록 군집이 잘 나뉨)."""
    scores = {k: silhouette_score(X, fcluster(Z, t=k, criterion="maxclust")) for k in k_range}
    return pd.Series(scores, name="silhouette").round(3)


def assign_clusters(points, Z, n_clusters):
    """덴드로그램을 n_clusters개로 잘라 'cluster' 칼럼 추가."""
    out = points.copy()
    out["cluster"] = fcluster(Z, t=n_clusters, criterion="maxclust")
    return out


def summarize_clusters(points, features=CLUSTER_FEATURES):
    """군집별 개수와 변수 평균."""
    agg = {"n": ("pitcher", "size")}
    agg.update({f: (f, "mean") for f in features})
    return points.groupby("cluster").agg(**agg).round(2)


def label_crosstab(points):
    """군집 안의 원래 구종 비율(%)."""
    return (pd.crosstab(points["cluster"], points["pitch_type"], normalize="index") * 100).round(1)


def find_label_mismatches(points):
    """군집의 다수 구종과 다른 이름표를 가진 점 (이름과 실제 움직임이 다른 공)."""
    majority = points.groupby("cluster")["pitch_type"].agg(lambda s: s.value_counts().index[0])
    out = points.copy()
    out["cluster_type"] = out["cluster"].map(majority)
    return out[out["pitch_type"] != out["cluster_type"]]


def pick_primary_pitch(points):
    """투수-시즌마다 가장 많이 던진 패스트볼 한 줄만 남긴다.

    FF/SI/FC를 두 개 이상 구사하는 투수는 구사율 1위 구종이 그 시즌의 대표값이 된다.
    """
    if "n_pitches" not in points.columns:
        raise KeyError('pick_primary_pitch는 unit="pitcher_season" 결과에만 사용할 수 있습니다.')
    out = (
        points.sort_values("n_pitches", ascending=False)
        .drop_duplicates(subset=["pitcher", "game_year"], keep="first")
        .sort_values(["game_year", "player_name"])
        .reset_index(drop=True)
    )
    print(f"투수-시즌 {len(out):,}개 (주 구종 기준, 원래 {len(points):,}개 중)")
    return out
