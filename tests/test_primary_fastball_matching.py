import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.preprocessing.cluster_pitcher_repertoire import (
    build_description_payload,
    summarize_pitcher_seasons,
)
from src.utils import llm_client as llm_module
from src.utils.find_nearest_pitcher import build_profile, find_nearest_pitcher


class PrimaryFastballMatchingTests(unittest.TestCase):
    def test_cluster_and_velocity_use_only_most_thrown_fastball(self):
        pitches = pd.DataFrame([
            {"pitcher": 1, "game_year": 2023, "pitch_type": pitch_type,
             "release_speed": velocity, "player_name": "Alpha", "p_throws": "R"}
            for pitch_type, velocity in [
                ("FF", 95), ("FF", 96), ("FF", 97), ("FF", 98),
                ("SI", 85), ("SI", 86), ("SI", 87),
            ]
        ])
        # Across all seven pitches C1 wins, but among the four FF pitches C0 wins.
        seasons = summarize_pitcher_seasons(pitches, np.array([0, 0, 0, 1, 1, 1, 1]), 2)
        season = seasons.iloc[0]
        self.assertEqual(season["primary_pitch_type"], "FF")
        self.assertEqual(season["n_pitches"], 4)
        self.assertEqual(season["cluster"], 0)
        self.assertAlmostEqual(season["average_velocity"], 96.5)
        self.assertAlmostEqual(season["cluster_share"], 0.75)
        self.assertEqual(build_description_payload(seasons)["1"]["2023"]["primary_pitch_type"], "FF")

    def test_profile_and_matching_use_primary_type_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "statcast_2023-03.csv"
            rows = [
                (1, "Alpha", "FF", -1.0, 6.0, 6.0, 40.0),
                (1, "Alpha", "FF", -1.2, 6.2, 6.2, 42.0),
                (1, "Alpha", "SI", -9.0, 9.0, 9.0, 90.0),
                (2, "Beta", "FC", -1.3, 6.3, 6.3, 43.0),
                (2, "Beta", "FC", -1.4, 6.4, 6.4, 44.0),
            ]
            pd.DataFrame(rows, columns=[
                "pitcher", "player_name", "pitch_type", "release_pos_x",
                "release_pos_z", "release_extension", "arm_angle",
            ]).assign(game_year=2023, p_throws="R").to_csv(raw_path, index=False)
            cluster_path = root / "pitcher_clustered.json"
            cluster_path.write_text(json.dumps({
                "1": {"2023": {"primary_pitch_type": "FF", "average_velocity": 96.5, "cluster": 0}},
                "2": {"2023": {"primary_pitch_type": "FC", "average_velocity": 96.0, "cluster": 0}},
            }), encoding="utf-8")
            fip_path = root / "fip.csv"
            pd.DataFrame([
                {"player_id": 1, "game_year": 2023, "FIP": 4.0, "IP": 100},
                {"player_id": 2, "game_year": 2023, "FIP": 3.0, "IP": 100},
            ]).to_csv(fip_path, index=False)

            with patch("src.utils.find_nearest_pitcher.find_raw_files", return_value=[raw_path]):
                profile = build_profile(cluster_file=cluster_path, fip_file=fip_path, save=False)

        alpha = profile.loc[profile["player_id"] == 1].iloc[0]
        self.assertEqual(alpha["primary_pitch_type"], "FF")
        self.assertAlmostEqual(alpha["release_pos_z"], 6.1)
        self.assertAlmostEqual(alpha["arm_angle"], 41.0)
        self.assertEqual(find_nearest_pitcher(1, 2023, profile=profile), (2, 2023))

    def test_ai_summary_uses_matching_primary_fastball(self):
        with tempfile.TemporaryDirectory() as directory:
            cluster_path = Path(directory) / "pitcher_clustered.json"
            cluster_path.write_text(json.dumps({
                "1": {"2023": {"primary_pitch_type": "SI", "average_velocity": 90.0, "cluster": 0}},
            }), encoding="utf-8")
            arsenal = pd.DataFrame([
                {"pitcher": 1, "game_year": 2023, "pitch_type": "FF", "primary_fastball": "FF",
                 "is_primary_fastball": True, "velo_mph": 95.0, "ivb_in": 15.0, "hb_in": 7.0},
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SI", "primary_fastball": "FF",
                 "is_primary_fastball": False, "velo_mph": 90.0, "ivb_in": 5.0, "hb_in": 12.0},
            ]).assign(velo_gap_vs_fb=0.0, ivb_gap_vs_fb=0.0, hb_gap_vs_fb=0.0)

            with patch.object(llm_module, "CLUSTER_FILE", cluster_path):
                aligned = llm_module.align_primary_fastballs(arsenal)

        self.assertEqual(aligned["primary_fastball"].tolist(), ["SI", "SI"])
        self.assertEqual(aligned["is_primary_fastball"].tolist(), [False, True])
        self.assertEqual(aligned["velo_gap_vs_fb"].tolist(), [5.0, 0.0])
        self.assertEqual(aligned["ivb_gap_vs_fb"].tolist(), [10.0, 0.0])

    def test_primary_fastball_movement_comes_from_corrected_pitch_data(self):
        with tempfile.TemporaryDirectory() as directory:
            processed_dir = Path(directory)
            movement_file = processed_dir / "2023_movement_reconciliation.csv"
            pd.DataFrame([
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SI", "ivb_ft": 10.0, "hb_ft": 20.0, "arm_angle": 40.0},
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SI", "ivb_ft": 14.0, "hb_ft": 24.0, "arm_angle": 42.0},
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SI", "ivb_ft": 99.0, "hb_ft": 99.0, "arm_angle": np.nan},
            ]).to_csv(movement_file, index=False)
            arsenal = pd.DataFrame([
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SI", "ivb_in": 5.0, "hb_in": 6.0, "velo_mph": 90.0},
                {"pitcher": 1, "game_year": 2023, "pitch_type": "SL", "ivb_in": -2.0, "hb_in": 3.0, "velo_mph": 80.0},
            ]).assign(primary_fastball="SI", is_primary_fastball=[True, False],
                     velo_gap_vs_fb=0.0, ivb_gap_vs_fb=0.0, hb_gap_vs_fb=0.0)
            corrected = llm_module.corrected_fastball_movements(arsenal, processed_dir)
            corrected_again = llm_module.corrected_fastball_movements(arsenal, processed_dir)
            cluster_path = processed_dir / "pitcher_clustered.json"
            cluster_path.write_text(json.dumps({"1": {"2023": {"primary_pitch_type": "SI"}}}), encoding="utf-8")
            with patch.object(llm_module, "CLUSTER_FILE", cluster_path):
                aligned = llm_module.align_primary_fastballs(corrected)

        self.assertEqual(corrected.loc[0, ["ivb_in", "hb_in"]].tolist(), [12.0, 22.0])
        self.assertEqual(corrected.loc[1, ["ivb_in", "hb_in"]].tolist(), [-2.0, 3.0])
        pd.testing.assert_frame_equal(corrected, corrected_again)
        self.assertEqual(aligned.loc[1, ["ivb_gap_vs_fb", "hb_gap_vs_fb"]].tolist(), [-7.0, -3.0])


if __name__ == "__main__":
    unittest.main()
