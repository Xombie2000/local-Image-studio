"""Discovery and explicit helper routing, without loading inference models."""
import io
import json
import sys
import unittest
from unittest import mock
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend


class ModelSelectionTests(unittest.TestCase):
    def test_parent_watchdog_requests_shutdown_after_reparenting(self):
        backend.SHUTTING_DOWN.clear()
        with mock.patch.object(backend.os, "getppid", return_value=999), mock.patch.object(
            backend, "request_shutdown"
        ) as shutdown:
            backend.watch_parent(parent_pid=123, poll_interval=0)
        shutdown.assert_called_once_with()

    def test_discovery_merges_providers_filters_non_chat_and_keeps_duplicate_ids(self):
        lms_items = [{"id": name} for name in ["qwen/qwen3-4b-2507", "flux2", "text-embedding-nomic", "qwen/qwen3-4b-2507"]]
        lms_items += [{"id": "unknown", "type": "embedding"}, {"id": "custom-chat", "capabilities": ["chat"]}]
        omlx_items = [{"id": "qwen/qwen3-4b-2507"}, {"id": "google/gemma-4"}, {"id": "audio", "capabilities": ["audio"]}]

        def response_for(url, *_args, **_kwargs):
            items = lms_items if ":1234/" in url else omlx_items
            return io.BytesIO(json.dumps({"data": items}).encode())

        with patch.object(backend.LMStudioPromptHelper, "request", side_effect=response_for):
            self.assertEqual(backend.LMStudioPromptHelper.available_models(), [
                "lms::qwen/qwen3-4b-2507",
                "lms::custom-chat",
                "omlx::qwen/qwen3-4b-2507",
                "omlx::google/gemma-4",
            ])

    def test_discovery_tolerates_either_server_being_offline(self):
        payload = io.BytesIO(json.dumps({"data": [{"id": "local-chat"}]}).encode())

        def only_omlx(url, *_args, **_kwargs):
            if ":1234/" in url:
                raise OSError("LM Studio is offline")
            return payload

        with patch.object(backend.LMStudioPromptHelper, "request", side_effect=only_omlx):
            self.assertEqual(backend.LMStudioPromptHelper.available_models(), ["omlx::local-chat"])

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

    def test_omlx_selection_routes_raw_model_id_to_omlx(self):
        helper = backend.LMStudioPromptHelper()
        payload = {"choices": [{"message": {"content": "A cat on a fence."}, "finish_reason": "stop"}]}
        selection = "omlx::qwen/local-chat"
        with patch.object(helper, "available_models", return_value=[selection]), \
             patch.object(helper, "request", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result = helper.improve("cat", "normal", model_id=selection)
        self.assertEqual(request.call_args.args[0], "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(json.loads(request.call_args.args[1])["model"], "qwen/local-chat")
        self.assertEqual(result.model, selection)

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
        with patch.object(backend.v1, "model_is_installed", return_value=True):
            for model in ("flux2_klein_4b", "flux2_klein_9b"):
                value = backend.validate_v2_payload({"prompt": "cat", "model_id": model, "prompt_helper_model": "chosen-chat"})
                self.assertEqual(value["model_id"], model)
                self.assertEqual(value["prompt_helper_model"], "chosen-chat")
