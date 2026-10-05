"""Bounded, real-pitch sample and GMM density regions for the comparison map.

The model has three features (IVB, arm-side HB, arm angle). A pitcher-season is
represented by one mean of all its FF/SI/FC pitches; its most common component
is retained separately. The point is not a single observed pitch or a GMM boundary.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.preprocessing.fit_pitch_gmm import default_model_path, load_model
from src.preprocessing.load_movement_data import DEFAULT_FEATURES, find_movement_files


PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
SCHEMA_VERSION = 2
SAMPLE_PER_CLUSTER = 180
CHUNK_SIZE = 150_000
_cache_lock = threading.Lock()


def _covariance_matrix(gmm, cluster: int) -> np.ndarray:
    covariance_type = gmm.covariance_type
    if covariance_type == "full":
        return gmm.covariances_[cluster]
    if covariance_type == "tied":
        return gmm.covariances_
    if covariance_type == "diag":
        return np.diag(gmm.covariances_[cluster])
    if covariance_type == "spherical":
        return np.eye(len(DEFAULT_FEATURES)) * gmm.covariances_[cluster]
    raise ValueError(f"지원하지 않는 GMM 공분산 형식: {covariance_type}")


def _component_regions(model) -> list[dict]:
    """1.5-standard-deviation density ellipsoids in original feature units."""
    centers = model.component_centers()
    scale = np.diag(model.scaler.scale_)
    regions = []
    for cluster, row in centers.iterrows():
        covariance = scale @ _covariance_matrix(model.gmm, int(cluster)) @ scale
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        # The symmetric square root maps a unit sphere into the density ellipsoid.
        shape = 1.5 * (eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0))) @ eigenvectors.T)
        regions.append({
            "id": int(cluster),
            "center": [round(float(row[feature]), 2) for feature in DEFAULT_FEATURES],
            "shape_matrix": np.round(shape, 4).tolist(),
            "n_pitches": 0,
        })
    return regions


def build_cluster_map_data(
    k: int,
    *,
    processed_dir: Path = PROCESSED_DIR,
    sample_per_cluster: int = SAMPLE_PER_CLUSTER,
    chunk_size: int = CHUNK_SIZE,
) -> dict:
    """Build or load the GMM map; never send all ~1.8m pitches to the browser."""
    if sample_per_cluster < 1:
        raise ValueError("sample_per_cluster must be positive")
    processed_dir = Path(processed_dir)
    model_path = default_model_path(k, processed_dir)
    files = find_movement_files(processed_dir)
    sources = [model_path, *files.values()]
    if not model_path.is_file():
        raise FileNotFoundError(f"GMM 모델이 없습니다: {model_path}")
    cache_file = processed_dir / f"cluster_map_k{k}_v{SCHEMA_VERSION}.json"
    newest_source = max(path.stat().st_mtime for path in sources)

    with _cache_lock:
        if cache_file.is_file() and cache_file.stat().st_mtime >= newest_source:
            with cache_file.open(encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("schema_version") == SCHEMA_VERSION and cached.get("sample_per_cluster") == sample_per_cluster:
                return cached

        model = load_model(model_path)
        if tuple(model.features) != DEFAULT_FEATURES:
            raise ValueError(f"지도에 필요한 GMM 피처가 아닙니다: {model.features}")
        regions = _component_regions(model)
        rng = np.random.default_rng(42)
        samples: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        # (pitcher, year, component) -> [number of pitches, IVB sum, HB sum, angle sum]
        pitcher_stats: dict[tuple[int, int, int], np.ndarray] = defaultdict(lambda: np.zeros(4, dtype=float))
        total_pitches = 0
        columns = ["pitcher", "game_year", "pitch_type", *DEFAULT_FEATURES]

        for path in files.values():
            for chunk in pd.read_csv(path, usecols=columns, chunksize=chunk_size, low_memory=False):
                chunk = chunk[chunk["pitch_type"].isin(("FF", "SI", "FC"))].copy()
                for column in ["pitcher", "game_year", *DEFAULT_FEATURES]:
                    chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
                chunk = chunk.dropna(subset=["pitcher", "game_year", *DEFAULT_FEATURES])
                if chunk.empty:
                    continue
                values = chunk[list(DEFAULT_FEATURES)].to_numpy(dtype=float)
                labels = model.predict(chunk)
                total_pitches += len(chunk)

                for cluster in range(model.n_components):
                    positions = np.flatnonzero(labels == cluster)
                    count = len(positions)
                    regions[cluster]["n_pitches"] += count
                    if not count:
                        continue
                    priorities = rng.random(count)
                    take = min(sample_per_cluster, count)
                    candidate_indices = np.argpartition(priorities, take - 1)[:take]
                    candidate_keys = priorities[candidate_indices]
                    candidate_points = values[positions[candidate_indices]]
                    if cluster in samples:
                        previous_keys, previous_points = samples[cluster]
                        candidate_keys = np.concatenate((previous_keys, candidate_keys))
                        candidate_points = np.concatenate((previous_points, candidate_points))
                    keep = min(sample_per_cluster, len(candidate_keys))
                    keep_indices = np.argpartition(candidate_keys, keep - 1)[:keep]
                    samples[cluster] = candidate_keys[keep_indices], candidate_points[keep_indices]

                grouped = chunk.assign(cluster=labels).groupby(["pitcher", "game_year", "cluster"])
                for (pitcher, year, cluster), group in grouped:
                    stats = pitcher_stats[(int(pitcher), int(year), int(cluster))]
                    stats[0] += len(group)
                    stats[1:] += group[list(DEFAULT_FEATURES)].sum().to_numpy(dtype=float)

        if not total_pitches:
            raise ValueError("GMM 지도에 표시할 패스트볼 투구가 없습니다.")
        pitcher_totals: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(4, dtype=float))
        for (pitcher, year, _), stats in pitcher_stats.items():
            pitcher_totals[(pitcher, year)] += stats
        locations: dict[str, dict] = {}
        for (pitcher, year, cluster), stats in pitcher_stats.items():
            key = f"{pitcher}-{year}"
            count = int(stats[0])
            previous = locations.get(key)
            if previous and (previous["n_pitches"] > count or (previous["n_pitches"] == count and previous["cluster"] < cluster)):
                continue
            season_stats = pitcher_totals[(pitcher, year)]
            total_fastballs = int(season_stats[0])
            locations[key] = {
                "cluster": cluster,
                "point": np.round(season_stats[1:] / total_fastballs, 2).tolist(),
                "n_pitches": count,
                "total_fastballs": total_fastballs,
                "cluster_share_pct": round(100 * count / total_fastballs, 1),
            }

        points = [
            [*np.round(point, 2).tolist(), cluster]
            for cluster in range(model.n_components)
            for point in samples.get(cluster, ([], []))[1]
        ]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "k": int(k),
            "features": list(DEFAULT_FEATURES),
            "sample_per_cluster": sample_per_cluster,
            "total_pitches": total_pitches,
            "clusters": regions,
            "points": points,
            "pitcher_locations": locations,
        }
        processed_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        temporary.replace(cache_file)
        return payload


def comparison_cluster_map(
    k: int,
    input_pitcher: tuple[int, int],
    similar_pitcher: tuple[int, int],
    *,
    processed_dir: Path = PROCESSED_DIR,
) -> dict:
    """Return all components but only the two selected pitcher-season locations."""
    data = build_cluster_map_data(k, processed_dir=processed_dir)
    pitchers = []
    for role, (pitcher, year) in (("input", input_pitcher), ("similar", similar_pitcher)):
        location = data["pitcher_locations"].get(f"{pitcher}-{year}")
        if location is None:
            raise ValueError(f"투수 {pitcher}의 {year} 시즌 GMM 위치가 없습니다.")
        pitchers.append({"role": role, "player_id": pitcher, "year": year, **location})
    return {key: value for key, value in data.items() if key != "pitcher_locations"} | {"pitchers": pitchers}
