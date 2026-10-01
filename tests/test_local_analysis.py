import unittest
from unittest.mock import patch

import main
from src.utils.local_analysis import build_local_analysis


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
        self.assertIn("AI 생성 아님", answer["model"])
        self.assertIn("4.10", answer["response"]["summary"])
        self.assertIn("원인으로 단정할 수 없습니다", answer["response"]["summary"])

    def test_no_key_uses_local_explanation_without_calling_external_llm(self):
        with patch("src.utils.llm_client.resolve_provider", return_value=("none", None)), \
             patch("main.build_profiles", return_value=(PROFILES, None)), \
             patch("src.utils.llm_client.llm_client") as external:
            answer = main.call_llm_client((1, 2023), (2, 2023))
        self.assertEqual(answer["source"], "rule_based")
        external.assert_not_called()


if __name__ == "__main__":
    unittest.main()
