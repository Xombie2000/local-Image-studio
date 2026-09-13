"""Krea 2 registry, routing, persistence, cleanup, and lineage regressions."""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_v2 as backend
import mflux_worker


class KreaRegistryTests(unittest.TestCase):
    def test_registry_entry(self):
        definition = backend.v1.MODEL_DEFINITIONS[backend.KREA_MODEL_ID]
        self.assertEqual(definition["label"], "Krea 2 Turbo")
        self.assertEqual(definition["cache_name"], "models--krea--Krea-2-Turbo")

    def test_complete_snapshot_detection_and_missing_behavior_are_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = Path(directory)
            cache = hub / "models--krea--Krea-2-Turbo"
            revision = "test-revision"
            (cache / "refs").mkdir(parents=True)
            (cache / "refs/main").write_text(revision, encoding="utf-8")
            snapshot = cache / "snapshots" / revision
            for relative_path in backend.KREA_REQUIRED_FILES:
                path = snapshot / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with mock.patch.object(backend.v1, "HF_HUB", hub), mock.patch.object(
                backend.subprocess, "Popen"
            ) as popen, mock.patch.object(backend.urllib.request, "urlopen") as urlopen:
                self.assertTrue(backend.model_is_installed(backend.KREA_MODEL_ID))
                (snapshot / backend.KREA_REQUIRED_FILES[0]).unlink()
                self.assertFalse(backend.model_is_installed(backend.KREA_MODEL_ID))
            popen.assert_not_called()
            urlopen.assert_not_called()

    def test_defaults_validation_and_missing_model_error(self):
        payload = {"prompt": "cat", "model_id": backend.KREA_MODEL_ID}
        with mock.patch.object(backend.v1, "model_is_installed", return_value=True):
            config = backend.validate_v2_payload(payload)
        self.assertEqual(config["steps"], 8)
        self.assertEqual(config["quantization"], 8)
        self.assertEqual(config["model_id"], backend.KREA_MODEL_ID)

        with mock.patch.object(backend.v1, "model_is_installed", return_value=False):
            with self.assertRaisesRegex(ValueError, "not installed"):
                backend.validate_v2_payload(payload)

    def test_krea_reference_edit_fails_without_fallback(self):
        with mock.patch.object(backend.v1, "model_is_installed", return_value=True):
            with self.assertRaisesRegex(ValueError, "reference editing is not supported"):
                backend.validate_v2_payload(
                    {"prompt": "edit", "model_id": backend.KREA_MODEL_ID, "reference_generation_id": "source"}
                )


class KreaWorkerTests(unittest.TestCase):
    def tearDown(self):
        mflux_worker.MODEL = None
        mflux_worker.MODEL_KEY = None
        mflux_worker.MODEL_ID = None

    def test_worker_routes_to_krea_python_api(self):
        class FakeKrea:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config = types.ModuleType("mflux.models.common.config")
        fake_config.ModelConfig = types.SimpleNamespace(krea2=lambda: "krea-config")
        fake_krea = types.ModuleType("mflux.models.krea2")
        fake_krea.Krea2 = FakeKrea
        modules = {"mflux.models.common.config": fake_config, "mflux.models.krea2": fake_krea}
        with mock.patch.dict(sys.modules, modules):
            model = mflux_worker.ensure_model(
                {
                    "model_id": backend.KREA_MODEL_ID,
                    "quantization": 8,
                    "reference_paths": [],
                    "lora_paths": [],
                    "lora_scales": [],
                },
                "request",
            )
        self.assertIsInstance(model, FakeKrea)
        self.assertEqual(model.kwargs["model_config"], "krea-config")
        self.assertEqual(model.kwargs["quantize"], 8)

    def test_unload_after_generation_reports_cleanup_memory(self):
        events: list[dict] = []

        class Callbacks:
            in_loop: list = []
            before_loop: list = []
            after_loop: list = []
            interrupt: list = []

            def register(self, _reporter):
                pass

        class Generated:
            def save(self, path):
                Path(path).touch()

        class FakeModel:
            callbacks = Callbacks()

            def generate_image(self, **_kwargs):
                return Generated()

        fake_core = types.ModuleType("mlx.core")
        fake_core.set_cache_limit = lambda _limit: None
        fake_core.reset_peak_memory = lambda: None
        fake_core.clear_cache = lambda: None
        fake_core.get_peak_memory = lambda: 24_000_000_000
        fake_core.get_active_memory = lambda: 0 if mflux_worker.MODEL is None else 20_000_000_000
        fake_core.get_cache_memory = lambda: 0 if mflux_worker.MODEL is None else 1_000_000_000
        fake_mlx = types.ModuleType("mlx")
        fake_mlx.core = fake_core
        mflux_worker.MODEL = FakeModel()
        mflux_worker.MODEL_ID = backend.KREA_MODEL_ID
        mflux_worker.MODEL_KEY = (backend.KREA_MODEL_ID, 8, False, (), ())
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            sys.modules, {"mlx": fake_mlx, "mlx.core": fake_core}
        ), mock.patch.object(mflux_worker, "emit", side_effect=events.append):
            mflux_worker.generate(
                {
                    "request_id": "request",
                    "params": {
                        "model_id": backend.KREA_MODEL_ID,
                        "quantization": 8,
                        "prompt": "cat",
                        "width": 512,
                        "height": 512,
                        "steps": 8,
                        "outputs": [str(Path(directory) / "out.png")],
                        "seeds": [42],
                        "reference_paths": [],
                        "lora_paths": [],
                        "lora_scales": [],
                        "unload_after": True,
                    },
                }
            )
        result = next(event for event in events if event["event"] == "result")
        self.assertEqual(result["model_id"], backend.KREA_MODEL_ID)
        self.assertEqual(result["results"][0]["peak_memory_bytes"], 24_000_000_000)
        self.assertEqual(result["results"][0]["post_cleanup_active_memory_bytes"], 0)
        self.assertEqual(result["results"][0]["post_cleanup_cache_memory_bytes"], 0)


class KreaPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.patches = ExitStack()
        for owner, name, value in (
            (backend, "APP_SUPPORT", root / "Support"),
            (backend, "GENERATIONS_DIR", root / "Pictures"),
            (backend, "THUMBNAILS_DIR", root / "Support/Thumbnails"),
            (backend, "REFERENCES_DIR", root / "Support/References"),
            (backend, "LORAS_DIR", root / "Support/LoRAs"),
            (backend, "DATABASE_PATH", root / "Support/history.sqlite3"),
            (backend, "PROJECT_ARCHIVES_DIR", root / "Pictures/Archives"),
            (backend.v1, "APP_SUPPORT", root / "Support"),
            (backend.v1, "GENERATIONS_DIR", root / "Pictures"),
            (backend.v1, "THUMBNAILS_DIR", root / "Support/Thumbnails"),
            (backend.v1, "REFERENCES_DIR", root / "Support/References"),
            (backend.v1, "LORAS_DIR", root / "Support/LoRAs"),
            (backend.v1, "DATABASE_PATH", root / "Support/history.sqlite3"),
        ):
            self.patches.enter_context(mock.patch.object(owner, name, value))
        self.patches.enter_context(mock.patch.dict(os.environ, {"LIS_TEST_MODE": "1"}))
        self.patches.enter_context(mock.patch.object(backend.v1, "model_is_installed", return_value=True))
        self.patches.enter_context(
            mock.patch.object(
                backend.v1,
                "fake_test_image",
                side_effect=lambda path: Image.new("RGB", (768, 768), "slategray").save(path),
            )
        )
        self.patches.enter_context(
            mock.patch.object(
                backend.v1,
                "create_thumbnail",
                side_effect=lambda source, target: Image.open(source).convert("RGB").save(target, "JPEG"),
            )
        )
        backend.JOBS.clear()
        backend.ACTIVE_JOB_ID = None
        backend.ensure_directories()
        backend.initialize_database()

    def tearDown(self):
        backend.JOBS.clear()
        backend.ACTIVE_JOB_ID = None
        backend.cancel_idle_timer()
        self.patches.close()
        self.temporary.cleanup()

    @staticmethod
    def wait_for(job_id: str) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with backend.JOBS_LOCK:
                job = backend.JOBS[job_id].copy()
            if job["state"] in {"complete", "error"}:
                return job
            time.sleep(0.01)
        raise AssertionError("job timed out")

    def test_metadata_persistence_and_seedvr2_child_lineage(self):
        project = backend.create_project("Krea Test")
        source_job = backend.start_generation(
            {
                "prompt": "exact visible prompt",
                "prompt_is_final": True,
                "model_id": backend.KREA_MODEL_ID,
                "width": 768,
                "height": 768,
                "random_seed": False,
                "seed": 123,
                "project_id": project["id"],
            }
        )
        source_job = self.wait_for(source_job["id"])
        self.assertEqual(source_job["state"], "complete", source_job["message"])
        source = source_job["generation"]
        self.assertEqual(source["model_id"], backend.KREA_MODEL_ID)
        self.assertEqual(source["model"], "Krea 2 Turbo")
        self.assertEqual(source["original_prompt"], "exact visible prompt")
        self.assertEqual(source["improved_prompt"], "exact visible prompt")
        self.assertEqual(source["quantization"], 8)
        self.assertEqual(source["steps"], 8)
        self.assertEqual((source["width"], source["height"]), (768, 768))
        self.assertEqual(source["project_id"], project["id"])

        class FakeUpscaleWorker:
            command_lock = threading.Lock()
            events: queue.Queue = queue.Queue()
            process = None

            @staticmethod
            def public_status():
                return {"status": "unloaded", "model_id": None, "active_memory_bytes": None}

            def _write(self, command):
                params = command["params"]
                with Image.open(params["image_path"]) as image:
                    image.resize((1536, 1536)).save(params["output_path"])
                self.events.put(
                    {
                        "event": "result",
                        "request_id": command["request_id"],
                        "output_path": params["output_path"],
                        "generation_time": 0.1,
                        "peak_memory_bytes": 1,
                    }
                )

            def unload(self):
                pass

        fake_worker = FakeUpscaleWorker()
        with mock.patch.object(backend, "WORKER", fake_worker), mock.patch.object(
            backend, "seedvr2_is_installed", return_value=True
        ):
            child_job = backend.start_upscale(
                {
                    "source_generation_id": source["id"],
                    "project_id": project["id"],
                    "scale": "2x",
                }
            )
            child_job = self.wait_for(child_job["id"])
        self.assertEqual(child_job["state"], "complete", child_job["message"])
        child = child_job["generation"]
        self.assertEqual(child["parent_id"], source["id"])
        self.assertEqual(child["project_id"], project["id"])
        self.assertEqual(child["model_id"], backend.SEEDVR2_MODEL_ID)
        self.assertEqual((child["upscale_source_width"], child["upscale_source_height"]), (768, 768))
        self.assertEqual(child["upscale_scale_factor"], "2×")
        persisted_source = backend.public_generation(backend.generation_row(source["id"]))
        self.assertEqual(persisted_source["model_id"], backend.KREA_MODEL_ID)
        self.assertEqual((persisted_source["width"], persisted_source["height"]), (768, 768))


if __name__ == "__main__":
    unittest.main()
