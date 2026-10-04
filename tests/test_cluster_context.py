import unittest
from unittest.mock import Mock, patch

import pandas as pd

import main


class ClusterContextTests(unittest.TestCase):
    def test_gmm_center_is_reported_in_original_inch_and_degree_units(self):
        model = Mock()
        model.component_centers.return_value = pd.DataFrame(
            {"ivb_ft": [15.84], "hb_ft": [9.56], "arm_angle": [36.74]},
            index=[4],
        )
        main._cluster_centers.cache_clear()
        with patch("src.preprocessing.fit_pitch_gmm.load_model", return_value=model):
            centers = main._cluster_centers(6)
        self.assertEqual(centers[4], {
            "ivb_in": 15.8,
            "hb_in": 9.6,
            "arm_angle_deg": 36.7,
        })
        main._cluster_centers.cache_clear()


if __name__ == "__main__":
    unittest.main()
