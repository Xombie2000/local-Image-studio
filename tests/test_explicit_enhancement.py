"""Explicit editor enhancement is separate from final image prompts."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend


class ExplicitEnhancementTests(unittest.TestCase):
    def test_enhance_uses_exact_input_and_selected_helper_without_image_job(self):
        original = "  exactly eight wheels, no visible weapons\nTokyo at night  "
        result = backend.PromptHelperResult(original + ", rain", model="exact-helper", tokens_per_second=12, token_count=24, total_time=2)
        with patch.object(backend.PROMPT_HELPER, "improve", return_value=result) as improve, \
             patch.object(backend, "start_generation") as generate:
            response = backend.enhance_prompt({"prompt": original, "model_id": "exact-helper", "strength": "strong"})
        improve.assert_called_once_with(original, "strong", model_id="exact-helper")
        generate.assert_not_called()
        self.assertTrue(response["enhanced"])
        self.assertEqual(response["prompt"], result.prompt)
        self.assertEqual(response["prompt_helper"]["tokens_per_second"], 12)

    def test_failure_preserves_original_and_reports_nonblocking_notice(self):
        for outcome in (
            backend.PromptHelperResult("different", notice="unavailable"),
            backend.PromptHelperResult(None, model="broken-helper"),
            RuntimeError("test failure"),
        ):
            with self.subTest(outcome=type(outcome).__name__), patch.object(backend.PROMPT_HELPER, "improve") as improve:
                if isinstance(outcome, Exception):
                    improve.side_effect = outcome
                else:
                    improve.return_value = outcome
                result = backend.enhance_prompt({"prompt": "  original\n", "model_id": "missing"})
                self.assertFalse(result["enhanced"])
                self.assertEqual(result["prompt"], "  original\n")
                self.assertTrue(result["notice"])

    def test_noop_response_is_not_reported_as_an_enhancement(self):
        original = "A polished prompt with soft studio lighting."
        for returned in (original, "  A polished prompt  with soft studio lighting.\n"):
            with self.subTest(returned=returned), patch.object(
                backend.PROMPT_HELPER,
                "improve",
                return_value=backend.PromptHelperResult(returned, model="exact-helper"),
            ):
                result = backend.enhance_prompt({"prompt": original, "model_id": "exact-helper"})
            self.assertFalse(result["enhanced"])
            self.assertEqual(result["prompt"], original)
            self.assertIn("no useful changes", result["notice"])
            self.assertEqual(result["prompt_helper"]["model"], "exact-helper")

    def test_final_prompt_disables_both_hidden_rewrite_paths_and_keeps_whitespace(self):
        original = "  current editor: 日本語\nexactly eight wheels; no visible weapons  "
        with patch.object(backend.v1, "model_is_installed", return_value=True):
            config = backend.validate_v2_payload({"prompt": original, "prompt_is_final": True,
                "prompt_improvement": True, "improved_prompt_override": "hidden old prompt"})
        self.assertEqual(config["prompt"], original)
        self.assertFalse(config["prompt_improvement"])
        self.assertIsNone(config["improved_prompt_override"])


if __name__ == "__main__":
    unittest.main()
