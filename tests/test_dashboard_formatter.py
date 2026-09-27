import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.visualization.dashboard_formatter import (
    PitchCsvError,
    available_pitchers,
    build_visualization_data,
    discover_pitch_csvs,
    read_pitch_csvs,
    write_visualization_json,
)


def statcast_row(name="Shohei Ohtani", pitch_type="FF"):
    return {
        "player_name": name,
        "pitcher": "660271",
        "game_pk": "123",
        "at_bat_number": "4",
        "pitch_number": "2",
        "game_year": "2024",
        "pitch_type": pitch_type,
        "pitch_name": "4-Seam Fastball" if pitch_type == "FF" else "Slider",
        "release_speed": "95.0",
        "release_pos_x": "-1.85",
        "release_pos_y": "54.4",
        "release_pos_z": "5.95",
        "plate_x": "0.42",
        "plate_z": "2.71",
        "vx0": "7.2",
        "vy0": "-138.0",
        "vz0": "-4.5",
        "ax": "-8.0",
        "ay": "30.0",
        "az": "-15.0",
        "pfx_x": "-0.7",
        "pfx_z": "1.2",
    }


class DashboardFormatterTests(unittest.TestCase):
    def test_discovers_only_data_prefixed_csv_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "data_ohtani.csv").touch()
            (directory / "pitch_data.csv").touch()
            (directory / "data_notes.json").touch()

            found = discover_pitch_csvs(directory)

            self.assertEqual([path.name for path in found], ["data_ohtani.csv"])

    def test_reads_utf8_csv_and_builds_pitcher_payload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "data_pitchers.csv"
            rows = [statcast_row(), statcast_row("Justin Verlander", "SL")]
            with path.open("w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            loaded = read_pitch_csvs([path])
            payload = build_visualization_data(
                loaded, pitcher="shohei ohtani", samples=5
            )

            self.assertEqual(
                available_pitchers(loaded), ["Justin Verlander", "Shohei Ohtani"]
            )
            self.assertEqual(payload["pitcher"]["name"], "Shohei Ohtani")
            self.assertEqual(payload["pitch_count"], 1)
            self.assertEqual(payload["pitch_types"][0]["code"], "FF")
            self.assertEqual(len(payload["trajectories"][0]["points"]), 5)
            self.assertAlmostEqual(
                payload["trajectories"][0]["points"][-1]["z"], 0
            )

    def test_requires_pitcher_when_multiple_are_present(self):
        with self.assertRaisesRegex(PitchCsvError, "--pitcher"):
            build_visualization_data(
                [statcast_row(), statcast_row("Justin Verlander")]
            )

    def test_invalid_rows_are_reported_without_hiding_valid_rows(self):
        invalid = statcast_row()
        invalid["plate_x"] = ""
        payload = build_visualization_data([statcast_row(), invalid], samples=3)

        self.assertEqual(payload["pitch_count"], 1)
        self.assertEqual(len(payload["skipped"]), 1)
        self.assertIn("plate_x", payload["skipped"][0]["reason"])

    def test_json_writer_preserves_korean_text(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "nested" / "pitch-data.json"
            write_visualization_json({"pitcher": "오타니"}, destination)

            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8"))["pitcher"],
                "오타니",
            )


if __name__ == "__main__":
    unittest.main()
