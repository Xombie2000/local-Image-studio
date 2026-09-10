"""Real HTTP/storage project lifecycle; the existing test worker avoids inference."""
import json
import os
import select
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path


class ProjectRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        hf_cache = cls.root / "hf-cache"
        model_cache = hf_cache / "models--black-forest-labs--FLUX.2-klein-4B"
        snapshot = model_cache / "snapshots/test-revision"
        for relative_path in (
            "transformer/config.json",
            "text_encoder/config.json",
            "vae/config.json",
        ):
            path = snapshot / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (model_cache / "refs").mkdir(parents=True, exist_ok=True)
        (model_cache / "refs/main").write_text("test-revision", encoding="utf-8")
        env = dict(os.environ, LIS_APP_SUPPORT=str(cls.root / "support"),
                   LIS_GENERATIONS_DIR=str(cls.root / "images"), HF_HUB_CACHE=str(hf_cache),
                   LIS_TEST_MODE="1", PYTHONUNBUFFERED="1")
        cls.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "backend_v2.py"), "--port", "0", "--token", "project-tests"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.cleanup)
        if not select.select([cls.process.stdout], [], [], 20)[0]:
            raise RuntimeError("Project test backend did not start")
        ready = cls.process.stdout.readline().split()
        if not ready or ready[0] != "READY":
            diagnostics = cls.process.stderr.read() if cls.process.poll() is not None else ""
            raise RuntimeError(f"Unexpected startup: {ready}\n{diagnostics}")
        cls.url = f"http://127.0.0.1:{ready[1]}"

    @classmethod
    def cleanup(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
        cls.process.stdout.close()
        cls.process.stderr.close()
        cls.temp.cleanup()

    def request(self, path, data=None, method=None):
        request = urllib.request.Request(self.url + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", "X-Local-Image-Studio-Token": "project-tests"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def generate(self, project_id, **extra):
        payload = {"prompt": "A military attack drone from 2100", "model_id": "flux2_klein_4b",
                   "project_id": project_id, "width": 512, "height": 512, "steps": 4,
                   "prompt_improvement": False, "model_retention": "immediate"}
        payload.update(extra)
        status, job = self.request("/api/generate", payload)
        self.assertEqual(status, 202, job)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            _, result = self.request(f"/api/jobs/{job['id']}")
            if result["state"] in ("complete", "error"):
                self.assertEqual(result["state"], "complete", result)
                return result["generation"]
            time.sleep(0.02)
        self.fail("Project generation did not complete")

    def test_create_then_immediate_generation_uses_persisted_id(self):
        status, project = self.request("/api/projects", {"name": "Immediate"})
        self.assertEqual(status, 201)
        with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects WHERE id=?", (project["id"],)).fetchone(), ("Immediate",))
        generation = self.generate(project["id"])
        self.assertEqual(generation["project_id"], project["id"])
        self.assertIsNone(generation["parent_id"])
        self.assertTrue(Path(generation["image_path"]).is_file())
        with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT project_id FROM generations WHERE id=?", (generation["id"],)).fetchone(), (project["id"],))

    def test_deleted_project_rejected_and_recreated_name_has_new_id(self):
        _, old = self.request("/api/projects", {"name": "Recreated"})
        self.assertEqual(self.request(f"/api/projects/{old['id']}", method="DELETE")[0], 200)
        _, new = self.request("/api/projects", {"name": "Recreated"})
        self.assertNotEqual(old["id"], new["id"])
        status, response = self.request("/api/generate", {"prompt": "cat", "project_id": old["id"]})
        self.assertEqual(status, 400)
        self.assertEqual(response, {"error": "Project not found."})
        self.assertEqual(self.generate(new["id"])["project_id"], new["id"])

    def test_all_images_new_generation_has_no_project(self):
        self.assertIsNone(self.generate(None)["project_id"])

    def test_final_editor_prompt_survives_http_and_database_exactly(self):
        for text in ("  edited enhancement\nNo lettering.  ", "original restored\n", "Helper Off: 日本語"):
            with self.subTest(prompt=text):
                generation = self.generate(None, prompt=text, prompt_is_final=True,
                    prompt_improvement=True, improved_prompt_override="must never be used")
                self.assertEqual(generation["original_prompt"], text)
                self.assertEqual(generation["improved_prompt"], text)
                self.assertIsNone(generation["prompt_helper"]["model"])
                with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
                    self.assertEqual(connection.execute("SELECT prompt FROM generations WHERE id=?", (generation["id"],)).fetchone(), (text,))

    def test_project_delete_preserves_images_and_image_delete_reattaches_children(self):
        _, project = self.request("/api/projects", {"name": "Delete Actions"})
        parent = self.generate(project["id"])
        child = self.generate(project["id"], parent_id=parent["id"])
        grandchild = self.generate(project["id"], parent_id=child["id"])
        self.assertEqual(self.request(f"/api/generations/{child['id']}", method="DELETE")[0], 200)
        self.assertFalse(Path(child["image_path"]).exists())
        with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT parent_id FROM generations WHERE id=?", (grandchild["id"],)).fetchone(), (parent["id"],))
        self.assertEqual(self.request(f"/api/projects/{project['id']}", method="DELETE")[0], 200)
        with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
            for generation in (parent, grandchild):
                row = connection.execute("SELECT project_id,image_path FROM generations WHERE id=?", (generation["id"],)).fetchone()
                self.assertIsNone(row[0])
                self.assertTrue(Path(row[1]).is_file())

    def test_unavailable_enhance_returns_prompt_without_generation(self):
        status, result = self.request("/api/prompt/enhance", {"prompt": "unchanged draft", "model_id": "off"})
        self.assertEqual(status, 200)
        self.assertFalse(result["enhanced"])
        self.assertEqual(result["prompt"], "unchanged draft")
        with closing(sqlite3.connect(self.root / "support/history.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM generations WHERE original_prompt=?", ("unchanged draft",)).fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
