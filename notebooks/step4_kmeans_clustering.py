"""
4단계: 표준화 -> K-Means 클러스터링 (k 탐색 포함)
--------------------------------------------------
입력: data/processed/interim/fastball_profile_table.pkl (3단계 산출물)
출력:
  - data/processed/output/fastball_clusters.csv   (투수-시즌 + 클러스터 라벨)
  - data/processed/output/kmeans_k_selection.csv   (k별 inertia, silhouette)
  - data/processed/output/kmeans_k_selection.png   (elbow / silhouette 그래프)
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

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
OUTPUT_DIR = ROOT / "data" / "processed" / "output"
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

FEATURE_COLS = [
    "release_speed",
    "ivb_ft",
    "hb_ft",
    "arm_angle",
    "release_pos_x",
    "release_pos_z",
    "release_extension",
]

K_CANDIDATES = range(2, 11)   # k=2 ~ 10 탐색
RANDOM_STATE = 42


def select_k(X_scaled: np.ndarray) -> pd.DataFrame:
    rows = []
    for k in K_CANDIDATES:
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)
        labels = km.fit_predict(X_scaled)
        sil = silhouette_score(X_scaled, labels)
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": sil})
        print(f"  k={k}: inertia={km.inertia_:.1f}, silhouette={sil:.3f}")
    return pd.DataFrame(rows)


def plot_k_selection(k_table: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(k_table["k"], k_table["inertia"], marker="o")
    axes[0].set_xlabel("k")
    axes[0].set_ylabel("inertia")
    axes[0].set_title("Elbow")

    axes[1].plot(k_table["k"], k_table["silhouette"], marker="o", color="darkorange")
    axes[1].set_xlabel("k")
    axes[1].set_ylabel("silhouette score")
    axes[1].set_title("Silhouette")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"그래프 저장: {out_path}")


if __name__ == "__main__":
    profile = pd.read_pickle(INTERIM_DIR / "fastball_profile_table.pkl")

    X = profile[FEATURE_COLS].to_numpy()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print("[select_k] k별 inertia / silhouette 계산 중...")
    k_table = select_k(X_scaled)
    k_table.to_csv(OUTPUT_DIR / "kmeans_k_selection.csv", index=False)
    plot_k_selection(k_table, OUTPUT_DIR / "kmeans_k_selection.png")

    # ---- silhouette 최고점을 잠정 k로 사용 (최종 k는 도메인 판단으로 조정 가능) ----
    best_k = int(k_table.loc[k_table["silhouette"].idxmax(), "k"])
    print(f"\n[final] silhouette 기준 잠정 k = {best_k}")

    final_km = KMeans(n_clusters=best_k, n_init=10, random_state=RANDOM_STATE)
    profile["cluster"] = final_km.fit_predict(X_scaled)

    out_path = OUTPUT_DIR / "fastball_clusters.csv"
    profile.to_csv(out_path, index=False)
    print(f"저장 완료: {out_path}")

    print("\n[클러스터별 평균 프로필]")
    print(profile.groupby("cluster")[FEATURE_COLS].mean().round(2))
    print("\n[클러스터별 표본 수]")
    print(profile["cluster"].value_counts().sort_index())

