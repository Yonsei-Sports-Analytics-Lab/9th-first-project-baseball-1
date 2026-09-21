"""군집분석 시각화. 정제된 DataFrame과 linkage 행렬을 받아 그림만 그린다."""
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram

HB_LABEL = "HB, flight-time adjusted (in, arm side +)"
IVB_LABEL = "IVB, flight-time adjusted (in)"


def _clean(ax):
    ax.spines[["top", "right"]].set_visible(False)


def plot_dendrogram(Z, p=30, title="Ward dendrogram - fastballs (ivb_ft, hb_ft, arm_angle)"):
    fig, ax = plt.subplots(figsize=(12, 5))
    dendrogram(Z, truncate_mode="lastp", p=p, leaf_rotation=90, ax=ax)
    ax.set_title(title)
    ax.set_xlabel("cluster size (merged leaves)")
    ax.set_ylabel("distance")
    fig.tight_layout()
    return fig


def plot_clusters(points):
    """군집별 색: HB-IVB, arm angle-IVB, arm angle-HB."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    cmap = plt.get_cmap("tab10")
    for i, (c, g) in enumerate(points.groupby("cluster")):
        axes[0].scatter(g["hb_ft"], g["ivb_ft"], s=10, alpha=0.5, color=cmap(i), label=f"C{c} (n={len(g)})")
        axes[1].scatter(g["arm_angle"], g["ivb_ft"], s=10, alpha=0.5, color=cmap(i))
        axes[2].scatter(g["arm_angle"], g["hb_ft"], s=10, alpha=0.5, color=cmap(i))

    axes[0].set(xlabel=HB_LABEL, ylabel=IVB_LABEL, title="movement by cluster")
    axes[0].axvline(0, color="grey", lw=0.8)
    axes[0].legend(frameon=False, fontsize=9, markerscale=2)
    axes[1].set(xlabel="arm angle (deg)", ylabel=IVB_LABEL, title="arm angle vs IVB")
    axes[2].set(xlabel="arm angle (deg)", ylabel=HB_LABEL, title="arm angle vs HB")
    for ax in axes:
        _clean(ax)
    fig.tight_layout()
    return fig


def plot_by_label(points):
    """비교용: 같은 점을 원래 구종 이름표로 색칠."""
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    cmap = plt.get_cmap("tab10")
    for i, (pt, g) in enumerate(points.groupby("pitch_type")):
        ax.scatter(g["hb_ft"], g["ivb_ft"], s=10, alpha=0.5, color=cmap(i), label=pt)
    ax.set(xlabel=HB_LABEL, ylabel=IVB_LABEL, title="same points, colored by original pitch label")
    ax.axvline(0, color="grey", lw=0.8)
    ax.legend(frameon=False, markerscale=2)
    _clean(ax)
    fig.tight_layout()
    return fig
