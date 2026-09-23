"""Discovery and explicit helper routing, without loading inference models."""
import io
import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend


class ModelSelectionTests(unittest.TestCase):
    def test_lm_studio_runtime_starts_and_stops_only_owned_processes(self):
        runtime = backend.LMStudioRuntime(Path("/fake/lms"))
        endpoint_states = iter([False, False, True])
        with patch.object(runtime, "endpoint_available", side_effect=lambda: next(endpoint_states)), \
             patch.object(runtime, "status", return_value=False), \
             patch.object(runtime, "action", return_value=True) as action, \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(os, "access", return_value=True):
            self.assertTrue(runtime.ensure_started())
            self.assertTrue(runtime.started_daemon)
            self.assertTrue(runtime.started_server)
            runtime.shutdown()
        self.assertEqual(action.call_args_list, [
            mock.call("daemon", "up", "--json"),
            mock.call("server", "start", "--port", "1234", "--bind", "127.0.0.1"),
            mock.call("server", "stop", timeout=8),
            mock.call("daemon", "down", timeout=8),
        ])

    def test_lm_studio_runtime_leaves_existing_server_running(self):
        runtime = backend.LMStudioRuntime(Path("/fake/lms"))
        with patch.object(runtime, "endpoint_available", return_value=True), \
             patch.object(runtime, "action") as action:
            self.assertTrue(runtime.ensure_started())
            runtime.shutdown()
        action.assert_not_called()

    def test_running_external_provider_prevents_lm_studio_launch(self):
        runtime = backend.LMStudioRuntime(Path("/fake/lms"))
        with patch.object(runtime, "provider_available", side_effect=lambda provider: provider == "ollama"), \
             patch.object(runtime, "action") as action:
            self.assertTrue(runtime.ensure_started())
            self.assertTrue(runtime.ensure_started("ollama"))
        action.assert_not_called()

    def test_unavailable_external_preference_does_not_launch_lm_studio(self):
        runtime = backend.LMStudioRuntime(Path("/fake/lms"))
        with patch.object(runtime, "provider_available", return_value=False), \
             patch.object(runtime, "action") as action:
            self.assertFalse(runtime.ensure_started("omlx"))
        action.assert_not_called()

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
        ollama_items = [{"id": "qwen3:8b"}, {"id": "nomic-embed-text"}]

        def response_for(url, *_args, **_kwargs):
            items = lms_items if ":1234/" in url else omlx_items if ":8000/" in url else ollama_items
            return io.BytesIO(json.dumps({"data": items}).encode())

        with patch.object(backend.LMStudioPromptHelper, "request", side_effect=response_for):
            self.assertEqual(backend.LMStudioPromptHelper.available_models(), [
                "lms::qwen/qwen3-4b-2507",
                "lms::custom-chat",
                "omlx::qwen/qwen3-4b-2507",
                "omlx::google/gemma-4",
                "ollama::qwen3:8b",
            ])

    def test_discovery_tolerates_either_server_being_offline(self):
        payload = io.BytesIO(json.dumps({"data": [{"id": "local-chat"}]}).encode())

        def only_omlx(url, *_args, **_kwargs):
            if ":8000/" not in url:
                raise OSError("Other provider is offline")
            return payload

        with patch.object(backend.LMStudioPromptHelper, "request", side_effect=only_omlx):
            self.assertEqual(backend.LMStudioPromptHelper.available_models(), ["omlx::local-chat"])

    def test_ollama_selection_routes_through_openai_compatible_endpoint(self):
        helper = backend.LMStudioPromptHelper()
        payload = {"choices": [{"message": {"content": "A cat on a fence."}, "finish_reason": "stop"}]}
        selection = "ollama::qwen3:8b"
        with patch.object(helper, "available_models", return_value=[selection]), \
             patch.object(helper, "request", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result = helper.improve("cat", "normal", model_id=selection)
        self.assertEqual(request.call_args.args[0], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(json.loads(request.call_args.args[1])["model"], "qwen3:8b")
        self.assertEqual(result.model, selection)

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
