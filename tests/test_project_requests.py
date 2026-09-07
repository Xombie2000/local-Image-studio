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
from pathlib import Path


class ProjectRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        env = dict(os.environ, LIS_APP_SUPPORT=str(cls.root / "support"),
                   LIS_GENERATIONS_DIR=str(cls.root / "images"), LIS_TEST_MODE="1", PYTHONUNBUFFERED="1")
        cls.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "backend_v2.py"), "--port", "0", "--token", "project-tests"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        cls.addClassCleanup(cls.cleanup)
        if not select.select([cls.process.stdout], [], [], 20)[0]:
            raise RuntimeError("Project test backend did not start")
        ready = cls.process.stdout.readline().split()
        if not ready or ready[0] != "READY":
            raise RuntimeError(f"Unexpected startup: {ready}")
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

    def generate(self, project_id):
        payload = {"prompt": "A military attack drone from 2100", "model_id": "flux2_klein_4b",
                   "project_id": project_id, "width": 512, "height": 512, "steps": 4,
                   "prompt_improvement": False, "model_retention": "immediate"}
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
        with sqlite3.connect(self.root / "support/history.sqlite3") as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects WHERE id=?", (project["id"],)).fetchone(), ("Immediate",))
        generation = self.generate(project["id"])
        self.assertEqual(generation["project_id"], project["id"])
        self.assertIsNone(generation["parent_id"])
        self.assertTrue(Path(generation["image_path"]).is_file())
        with sqlite3.connect(self.root / "support/history.sqlite3") as connection:
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


if __name__ == "__main__":
    unittest.main()
