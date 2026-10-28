import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.visualization.comparison_data import pitcher_trajectory_data, sample_pitch_rows


class ComparisonDataTests(unittest.TestCase):
    def test_samples_only_requested_pitcher_and_regular_season(self):
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for month in (3, 4):
                path = Path(directory) / f"statcast_2023-{month:02}.csv"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["pitcher", "game_type", "pitch_type", "game_pk", "release_speed"])
                    writer.writeheader()
                    for index in range(7):
                        writer.writerow({"pitcher": "123", "game_type": "R", "pitch_type": "FF", "game_pk": f"{month}{index}", "release_speed": "95"})
                    writer.writerow({"pitcher": "123", "game_type": "P", "pitch_type": "SL", "game_pk": "postseason"})
                    writer.writerow({"pitcher": "999", "game_type": "R", "pitch_type": "CH", "game_pk": "other"})
                files.append(path)

            season_stats = {}
            rows = sample_pitch_rows(files, 123, per_type=3, season_stats=season_stats)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row["pitch_type"] == "FF" for row in rows))
            self.assertEqual(rows, sample_pitch_rows(files, 123, per_type=3))
            self.assertTrue(all("_source_file" in row for row in rows))
            self.assertEqual(season_stats["FF"], {"season_count": 14, "average_speed_mph": 95.0})
            self.assertNotIn("SL", season_stats)

    def test_trajectory_uses_full_season_usage_not_sample_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_year = root / "raw" / "2023"
            raw_year.mkdir(parents=True)
            path = raw_year / "statcast_2023-04.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["pitcher", "game_type", "pitch_type", "release_speed"])
                writer.writeheader()
                for pitch_type, speed in [("FF", 95), ("FF", 97), ("FF", 96), ("SL", 84)]:
                    writer.writerow({"pitcher": "123", "game_type": "R", "pitch_type": pitch_type, "release_speed": speed})

            stub = {
                "pitcher": {"name": "Test", "id": None},
                "pitch_types": [
                    {"code": "FF", "name": "Four-Seam", "count": 2, "average_speed_mph": 95.0},
                    {"code": "SL", "name": "Slider", "count": 1, "average_speed_mph": 84.0},
                ],
            }
            with patch("src.visualization.comparison_data.RAW_DIR", root / "raw"), \
                 patch("src.visualization.comparison_data.CACHE_DIR", root / "cache"), \
                 patch("src.visualization.comparison_data.build_visualization_data", return_value=stub):
                result = pitcher_trajectory_data(123, 2023)
                cached = pitcher_trajectory_data(123, 2023)

            self.assertEqual(result["season_pitch_count"], 4)
            self.assertEqual(result["pitch_types"][0]["season_count"], 3)
            self.assertEqual(result["pitch_types"][0]["usage_pct"], 75.0)
            self.assertEqual(result["pitch_types"][0]["average_speed_mph"], 96.0)
            self.assertEqual(result["pitch_types"][1]["usage_pct"], 25.0)
            self.assertEqual(cached, result)

    def test_season_modal_plate_bin_is_counted_and_real_pitch_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_year = root / "raw" / "2023"
            raw_year.mkdir(parents=True)
            path = raw_year / "statcast_2023-04.csv"
            fieldnames = [
                "pitcher", "game_type", "pitch_type", "game_year", "game_pk", "release_speed",
                "release_pos_x", "release_pos_z", "release_extension", "pfx_x", "pfx_z",
                "plate_x", "plate_z",
            ]
            locations = [(0.02, 2.40), (0.05, 2.42), (0.08, 2.43), (0.10, 2.44),
                         (-1.20, 1.40), (-0.80, 3.20), (0.80, 1.70), (1.20, 3.70)]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for index, (plate_x, plate_z) in enumerate(locations):
                    writer.writerow({
                        "pitcher": "123", "game_type": "R", "pitch_type": "FF", "game_year": "2023",
                        "game_pk": str(index), "release_speed": "95", "release_pos_x": "0",
                        "release_pos_z": "6", "release_extension": "6", "pfx_x": "0", "pfx_z": "0",
                        "plate_x": str(plate_x), "plate_z": str(plate_z),
                    })

            modal = {}
            rows = sample_pitch_rows([path], 123, per_type=3, modal_locations=modal)
            self.assertEqual(len(rows), 3)
            self.assertEqual(modal["FF"], {"plate_x": 0.125, "plate_z": 2.375, "count": 4, "grid_ft": 0.25})
            self.assertTrue(any(0 <= float(row["plate_x"]) < 0.25 and 2.25 <= float(row["plate_z"]) < 2.5 for row in rows))

            with patch("src.visualization.comparison_data.RAW_DIR", root / "raw"), \
                 patch("src.visualization.comparison_data.CACHE_DIR", root / "cache"):
                payload = pitcher_trajectory_data(123, 2023)
                cached = pitcher_trajectory_data(123, 2023)
            self.assertEqual(payload, cached)
            self.assertEqual(payload["trajectory_cache_version"], 2)
            self.assertEqual(payload["pitch_types"][0]["modal_plate_count"], 4)
            self.assertEqual(payload["pitch_types"][0]["modal_plate_x"], 0.125)
            self.assertEqual(payload["pitch_count"], 8)
            self.assertTrue(any(
                -0.25 < trajectory["points"][-1]["x"] <= 0
                and 2.25 <= trajectory["points"][-1]["y"] < 2.5
                for trajectory in payload["trajectories"]
            ))


if __name__ == "__main__":
    unittest.main()
