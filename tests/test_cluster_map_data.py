import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.preprocessing.fit_pitch_gmm import fit_pitch_gmm, save_model
from src.visualization.cluster_map_data import build_cluster_map_data, comparison_cluster_map


class ClusterMapDataTests(unittest.TestCase):
    def test_real_pitch_sample_regions_and_two_pitcher_locations(self):
        rng = np.random.default_rng(7)
        rows = []
        for pitcher, center in ((1, (16.0, 8.0, 50.0)), (2, (5.0, -10.0, 25.0))):
            for ivb, hb, angle in rng.normal(center, (0.5, 0.5, 0.8), size=(40, 3)):
                rows.append({
                    "pitcher": pitcher,
                    "game_year": 2023,
                    "pitch_type": "FF" if pitcher == 1 else "SI",
                    "ivb_ft": ivb,
                    "hb_ft": hb,
                    "arm_angle": angle,
                })
        frame = pd.DataFrame(rows)
        model = fit_pitch_gmm(frame, 2, fit_sample=None, n_init=1)
        borrowed = frame[frame["pitcher"] == 2].head(5).copy()
        borrowed["pitcher"] = 1
        frame = pd.concat([frame, borrowed], ignore_index=True)

        with tempfile.TemporaryDirectory() as directory:
            processed = Path(directory)
            save_model(model, processed / "pitch_type_gmm_k2.joblib")
            frame.to_csv(processed / "2023_movement_reconciliation.csv", index=False)
            data = build_cluster_map_data(2, processed_dir=processed, sample_per_cluster=5, chunk_size=13)
            cached = build_cluster_map_data(2, processed_dir=processed, sample_per_cluster=5, chunk_size=13)
            comparison = comparison_cluster_map(2, (1, 2023), (2, 2023), processed_dir=processed)

        self.assertEqual(data, cached)
        self.assertEqual(data["total_pitches"], 85)
        self.assertEqual(len(data["clusters"]), 2)
        self.assertEqual(sum(cluster["n_pitches"] for cluster in data["clusters"]), 85)
        self.assertEqual(len(data["points"]), 10)
        self.assertEqual(len(data["clusters"][0]["shape_matrix"]), 3)
        self.assertEqual(data["pitcher_locations"]["1-2023"]["total_fastballs"], 45)
        self.assertEqual(data["pitcher_locations"]["2-2023"]["total_fastballs"], 40)
        self.assertEqual(data["pitcher_locations"]["1-2023"]["primary_pitch_type"], "FF")
        self.assertEqual(data["pitcher_locations"]["1-2023"]["primary_pitch_count"], 40)
        expected_mean = frame[(frame["pitcher"] == 1) & (frame["pitch_type"] == "FF")][
            ["ivb_ft", "hb_ft", "arm_angle"]
        ].mean().to_numpy()
        np.testing.assert_allclose(data["pitcher_locations"]["1-2023"]["point"], expected_mean, atol=0.01)
        self.assertNotEqual(comparison["pitchers"][0]["cluster"], comparison["pitchers"][1]["cluster"])
        self.assertNotIn("pitcher_locations", comparison)


if __name__ == "__main__":
    unittest.main()
