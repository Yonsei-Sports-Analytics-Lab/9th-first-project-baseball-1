import unittest

from src.visualization.pitch_trajectory import (
    HOME_PLATE_FRONT_Y_FT,
    TrajectoryError,
    reconstruct_pitch_trajectory,
)


class PitchTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.statcast_pitch = {
            "game_year": 2024,
            "release_pos_x": -1.85,
            "release_pos_y": 54.4,
            "release_pos_z": 5.95,
            "plate_x": 0.42,
            "plate_z": 2.71,
            "release_speed": 95.0,
            "vx0": 7.2,
            "vy0": -138.0,
            "vz0": -4.5,
            "ax": -8.0,
            "ay": 30.0,
            "az": -15.0,
            "pfx_x": -0.7,
            "pfx_z": 1.2,
        }

    def test_statcast_model_preserves_measured_plate_location(self):
        result = reconstruct_pitch_trajectory(self.statcast_pitch, samples=51)

        self.assertEqual(result["method"], "statcast")
        self.assertEqual(len(result["points"]), 51)
        self.assertGreater(result["flight_time"], 0)
        self.assertEqual(result["points"][0]["time"], 0)
        self.assertAlmostEqual(result["points"][-1]["x"], 0.42)
        self.assertAlmostEqual(
            result["points"][-1]["y"], HOME_PLATE_FRONT_Y_FT, places=4
        )
        self.assertAlmostEqual(result["points"][-1]["z"], 2.71)
        self.assertTrue(
            all(
                first["y"] > second["y"]
                for first, second in zip(result["points"], result["points"][1:])
            )
        )

    def test_threejs_coordinates_match_pitch3d_axes(self):
        result = reconstruct_pitch_trajectory(
            self.statcast_pitch,
            samples=2,
            coordinate_system="threejs",
            precision=None,
        )
        endpoint = result["points"][-1]

        self.assertEqual(result["coordinate_system"], "threejs")
        self.assertAlmostEqual(endpoint["x"], -self.statcast_pitch["plate_x"])
        self.assertAlmostEqual(endpoint["y"], self.statcast_pitch["plate_z"])
        self.assertAlmostEqual(endpoint["z"], 0.0)

    def test_auto_falls_back_to_movement_model(self):
        aggregate = {
            key: self.statcast_pitch[key]
            for key in (
                "release_pos_x",
                "release_pos_y",
                "release_pos_z",
                "plate_x",
                "plate_z",
                "release_speed",
                "pfx_x",
                "pfx_z",
            )
        }
        result = reconstruct_pitch_trajectory(aggregate, samples=21, precision=None)

        self.assertEqual(result["method"], "movement")
        self.assertEqual(result["release_error_ft"], None)
        self.assertAlmostEqual(result["points"][0]["x"], aggregate["release_pos_x"])
        self.assertAlmostEqual(result["points"][0]["z"], aggregate["release_pos_z"])
        self.assertAlmostEqual(result["points"][-1]["x"], aggregate["plate_x"])
        self.assertAlmostEqual(result["points"][-1]["y"], HOME_PLATE_FRONT_Y_FT)
        self.assertAlmostEqual(result["points"][-1]["z"], aggregate["plate_z"])
        self.assertTrue(
            all(
                first["y"] > second["y"]
                for first, second in zip(result["points"], result["points"][1:])
            )
        )

    def test_inch_pfx_is_converted_only_when_requested(self):
        aggregate = {
            "release_pos_x": -1.5,
            "release_pos_y": 54.5,
            "release_pos_z": 6.0,
            "plate_x": 0.0,
            "plate_z": 2.5,
            "release_speed": 90.0,
            "pfx_x": 12.0,
            "pfx_z": 12.0,
        }
        feet = reconstruct_pitch_trajectory(aggregate, samples=3, precision=None)
        inches = reconstruct_pitch_trajectory(
            aggregate, samples=3, pfx_unit="inches", precision=None
        )

        self.assertNotAlmostEqual(feet["points"][1]["x"], inches["points"][1]["x"])
        self.assertNotAlmostEqual(feet["points"][1]["z"], inches["points"][1]["z"])

    def test_rejects_missing_release_distance(self):
        aggregate = {
            "release_pos_x": -1.5,
            "release_pos_z": 6.0,
            "plate_x": 0.0,
            "plate_z": 2.5,
            "release_speed": 90.0,
            "pfx_x": 0.0,
            "pfx_z": 1.0,
        }
        with self.assertRaises(TrajectoryError):
            reconstruct_pitch_trajectory(aggregate)


if __name__ == "__main__":
    unittest.main()
