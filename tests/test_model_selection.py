"""Discovery and explicit helper routing, without loading inference models."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend


class ModelSelectionTests(unittest.TestCase):
    def test_discovery_filters_non_chat_and_deduplicates(self):
        items = [{"id": name} for name in ["qwen/qwen3-4b-2507", "google/gemma-4", "flux2", "seedvr2_7b", "text-embedding-nomic", "qwen/qwen3-4b-2507"]]
        items += [{"id": "unknown", "type": "embedding"}, {"id": "audio", "capabilities": ["audio"]}, {"id": "custom-chat", "capabilities": ["chat"]}]
        with patch.object(backend.LMStudioPromptHelper, "request", return_value=io.BytesIO(json.dumps({"data": items}).encode())):
            self.assertEqual(backend.LMStudioPromptHelper.available_models(), ["qwen/qwen3-4b-2507", "google/gemma-4", "custom-chat"])

    def test_preferred_model_uses_discovered_exact_id(self):
        self.assertEqual(backend.LMStudioPromptHelper.choose_model(["qwen3.6-35b-a3b-mlx", "qwen/qwen3-4b-2507"]), "qwen/qwen3-4b-2507")

    def test_explicit_model_reaches_completion(self):
        helper = backend.LMStudioPromptHelper()
        payload = {"choices": [{"message": {"content": "A cat on a fence."}, "finish_reason": "stop"}], "usage": {"completion_tokens": 8}}
        with patch.object(helper, "available_models", return_value=["qwen/qwen3-4b-2507", "google/gemma-4"]), patch.object(helper, "request", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result = helper.improve("cat", "normal", model_id="google/gemma-4")
        self.assertEqual(json.loads(request.call_args.args[1])["model"], "google/gemma-4")
        self.assertEqual(result.model, "google/gemma-4")
        self.assertEqual(result.token_count, 8)

    def test_missing_selection_does_not_silently_switch_models(self):
        helper = backend.LMStudioPromptHelper()
        with patch.object(helper, "available_models", return_value=["some-other-model"]), patch.object(helper, "request") as request:
            result = helper.improve("exactly eight wheels, no visible weapons", "normal", model_id="missing")
        self.assertEqual(result.prompt, "exactly eight wheels, no visible weapons")
        self.assertIsNotNone(result.notice)
        request.assert_not_called()

    def test_off_does_not_contact_server(self):
        helper = backend.LMStudioPromptHelper()
        with patch.object(helper, "request") as request:
            result = helper.improve("original", "normal", model_id="off")
        self.assertEqual(result.prompt, "original")
        self.assertIsNone(result.notice)
        request.assert_not_called()

    def test_payload_preserves_each_image_and_helper_selection(self):
        for model in ("flux2_klein_4b", "flux2_klein_9b"):
            value = backend.validate_v2_payload({"prompt": "cat", "model_id": model, "prompt_helper_model": "chosen-chat"})
            self.assertEqual(value["model_id"], model)
            self.assertEqual(value["prompt_helper_model"], "chosen-chat")
