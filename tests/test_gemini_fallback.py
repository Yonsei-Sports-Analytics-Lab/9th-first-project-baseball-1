import unittest
from unittest.mock import Mock, patch

from src.utils.llm_client import call_llm_with_fallback


class GeminiFallbackTests(unittest.TestCase):
    def test_503_moves_to_next_model_after_one_retry(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            {"choices": [{"message": {"content": '{"status":"ok"}'}}]},
        ]
        with patch("src.utils.llm_client.resolve_provider", return_value=("gemini", "test-key")), \
             patch("src.utils.llm_client._sleep"):
            response, model = call_llm_with_fallback(
                [{"role": "user", "content": "test"}], client=client, model="gemini-3.8-flash"
            )
        self.assertEqual(model, "gemini-3.7-flash")
        self.assertEqual(response, {"status": "ok"})
        self.assertEqual(client.chat.completions.create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
