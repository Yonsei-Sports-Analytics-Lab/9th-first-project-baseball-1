import unittest
from unittest.mock import patch

import main
from src.utils.local_analysis import build_local_analysis
from src.utils.llm_client import transfer_targets, validate_response


PROFILES = {
    "input_pitcher": {"player_name": "Alpha", "primary_fastball": {"velo_mph": 95, "ivb_in": 15}},
    "similar_pitcher": {"player_name": "Beta", "primary_fastball": {"velo_mph": 94, "ivb_in": 14}},
    "search_context": {"input_fip": 4.1, "similar_fip": 3.3},
    "transfer_targets": [],
}


class LocalAnalysisTests(unittest.TestCase):
    def test_evidence_only_answer_is_not_labeled_as_ai(self):
        answer = build_local_analysis(PROFILES)
        self.assertEqual(answer["source"], "rule_based")
        self.assertEqual(answer["model"], "Statcast 관측값 기반 참고 분석")
        self.assertIn("4.10", answer["response"]["summary"])
        self.assertIn("원인으로 단정할 수 없습니다", answer["response"]["summary"])

    def test_no_key_uses_local_explanation_without_calling_external_llm(self):
        with patch("src.utils.llm_client.resolve_provider", return_value=("none", None)), \
             patch("main.build_profiles", return_value=(PROFILES, None)), \
             patch("src.utils.llm_client.llm_client") as external:
            answer = main.call_llm_client((1, 2023), (2, 2023))
        self.assertEqual(answer["source"], "rule_based")
        external.assert_not_called()

    def test_gemini_key_uses_external_analysis_branch(self):
        synthetic = {"model": "gemini-3.8-flash", "response": {"recommendations": []}}
        with patch("src.utils.llm_client.resolve_provider", return_value=("gemini", "test-key")), \
             patch("src.utils.llm_client.llm_client", return_value=synthetic) as external, \
             patch("main.build_search_context", return_value={"cluster": 2}):
            answer = main.call_llm_client((1, 2023), (2, 2023))
        self.assertIs(answer, synthetic)
        external.assert_called_once()

    def test_transient_gemini_error_uses_labeled_statcast_fallback(self):
        from src.utils.llm_client import TransientLLMError

        with patch("src.utils.llm_client.resolve_provider", return_value=("gemini", "test-key")), \
             patch("src.utils.llm_client.llm_client", side_effect=TransientLLMError("503")), \
             patch("main.build_profiles", return_value=(PROFILES, None)):
            answer = main.call_llm_client((1, 2023), (2, 2023))
        self.assertEqual(answer["source"], "rule_based")
        self.assertEqual(answer["fallback_reason"], "llm_unavailable")
        self.assertIn("일시적으로", answer["validation_warnings"][0])

    def test_fallback_only_recommends_secondary_pitches_and_shows_shape(self):
        profiles = {**PROFILES, "transfer_targets": [
            {"pitch_type": "FC", "pitch_name": "Cutter", "source_rv_per_100": 3.0},
            {"pitch_type": "SL", "pitch_name": "Slider", "source_n_pitches": 350,
             "source_usage_pct": 22.0, "source_rv_per_100": 1.2, "source_whiff_pct": 35.0,
             "source_small_sample": False,
             "target_shape": {"velo_mph": 85.0, "ivb_in": 2.0, "hb_in": -7.0}},
            {"pitch_type": "CU", "pitch_name": "Curveball", "source_n_pitches": 300,
             "source_rv_per_100": -4.1, "source_small_sample": False},
        ]}
        response = build_local_analysis(profiles)["response"]
        recommendations = response["recommendations"]
        self.assertEqual([item["pitch_type"] for item in recommendations], ["SL"])
        self.assertEqual([item["pitch_type"] for item in response["not_recommended"]], ["CU"])
        self.assertEqual(recommendations[0]["target_shape"]["hb_in"], -7.0)
        self.assertIn("RV/100 +1.2", recommendations[0]["rationale"][0])

    def test_transfer_target_and_validation_exclude_fastball_family(self):
        input_pitcher = {
            "primary_fastball": {"velo_mph": 95.0, "ivb_in": 15.0, "hb_in": 7.0},
            "arsenal": [{"pitch_type": "FF"}],
        }
        common = {"velo_gap_vs_fb": -5.0, "ivb_gap_vs_fb": -8.0,
                  "hb_gap_vs_fb": -4.0, "usage_pct": 20.0, "n_pitches": 300,
                  "small_sample": False, "rv_per_100": 1.2, "whiff_pct": 30.0}
        similar_pitcher = {"arsenal": [
            {**common, "pitch_type": "FC", "pitch_name": "Cutter"},
            {**common, "pitch_type": "SL", "pitch_name": "Slider"},
            {**common, "pitch_type": "CU", "pitch_name": "Curveball", "rv_per_100": -4.1},
        ]}
        targets = transfer_targets(input_pitcher, similar_pitcher)
        self.assertEqual([item["pitch_type"] for item in targets], ["SL", "CU"])
        warnings = validate_response(
            {"summary": "", "fastball_comparison": {}, "recommendations": [
                {"pitch_type": "FC", "action": "add", "rationale": ["300구"]},
                {"pitch_type": "CU", "action": "add", "rationale": ["300구"]}],
             "failure_cases": [], "not_recommended": [], "data_limitations": []},
            {"input_pitcher": input_pitcher, "similar_pitcher": similar_pitcher,
             "transfer_targets": targets},
        )
        self.assertTrue(any("FC" in warning for warning in warnings))
        self.assertTrue(any("CU" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
