#!/usr/bin/env python3
"""Local Image Studio v2 native-app backend.

This extends the proven v1 storage and validation layer while keeping the native
SwiftUI process small. Inference lives in a private persistent MFLUX worker so a
selected model can remain resident and be explicitly unloaded.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import queue
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from PIL import Image


RESOURCE_DIR = Path(__file__).resolve().parent
PARENT_DIR = RESOURCE_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
import backend as v1  # noqa: E402


APP_NAME = v1.APP_NAME
APP_SUPPORT = v1.APP_SUPPORT
GENERATIONS_DIR = v1.GENERATIONS_DIR
THUMBNAILS_DIR = v1.THUMBNAILS_DIR
REFERENCES_DIR = v1.REFERENCES_DIR
LORAS_DIR = v1.LORAS_DIR
DATABASE_PATH = v1.DATABASE_PATH
PROJECT_ARCHIVES_DIR = GENERATIONS_DIR / "Archives"
WORKER_PATH = RESOURCE_DIR / "mflux_worker.py"
MFLUX_PYTHON = Path(os.environ.get("LIS_MFLUX_PYTHON", Path.home() / ".local/share/uv/tools/mflux/bin/python"))
RETENTION_SECONDS = float(os.environ.get("LIS_RETENTION_SECONDS", "300"))
ARCHIVE_MANIFEST_NAME = ".lisarchive.json"
ARCHIVE_IMAGE_CODEC = "Lossless WebP (method 6)"

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
ACTIVE_JOB_ID: str | None = None
SHUTTING_DOWN = threading.Event()
SERVER: ThreadingHTTPServer | None = None
IDLE_TIMER: threading.Timer | None = None


@contextlib.contextmanager
def database():
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def ensure_directories() -> None:
    v1.ensure_directories()
    PROJECT_ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)


def add_column_if_missing(connection: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def initialize_database() -> None:
    v1.initialize_database()
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                package_path TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                archive_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS projects_name_idx ON projects(name COLLATE NOCASE);
            """
        )
        additions = (
            "parent_id TEXT",
            "project_id TEXT",
            "original_prompt TEXT",
            "improved_prompt TEXT",
            "prompt_improvement_model TEXT",
            "prompt_improvement_strength TEXT",
            "prompt_helper_time REAL",
            "reference_source_id TEXT",
            "reference_image_path TEXT",
            "variant_group_id TEXT",
            "variant_index INTEGER NOT NULL DEFAULT 1",
            "variant_count INTEGER NOT NULL DEFAULT 1",
            "generation_group_id TEXT",
        )
        for definition in additions:
            add_column_if_missing(connection, "generations", definition)
        connection.execute("UPDATE generations SET original_prompt = prompt WHERE original_prompt IS NULL")
        connection.execute("UPDATE generations SET improved_prompt = prompt WHERE improved_prompt IS NULL")
        connection.execute("UPDATE generations SET variant_group_id = id WHERE variant_group_id IS NULL")
        connection.execute("UPDATE generations SET generation_group_id = id WHERE generation_group_id IS NULL")
        connection.execute(
            """
            UPDATE generations
            SET reference_image_path = (
                SELECT source.image_path FROM generations AS source
                WHERE source.id = generations.reference_source_id
            )
            WHERE reference_source_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM generations AS source
                  WHERE source.id = generations.reference_source_id
              )
            """
        )
        # Add upscale metadata columns (v3)
        for col in ("upscale_source_width INTEGER NOT NULL DEFAULT 0", "upscale_source_height INTEGER NOT NULL DEFAULT 0", "upscale_scale_factor TEXT", "upscale_model_variant TEXT", "upscale_precision TEXT"):
            add_column_if_missing(connection, "generations", col)
        connection.execute("PRAGMA user_version = 3")
        active_projects = connection.execute("SELECT * FROM projects WHERE archived = 0").fetchall()
    for project in active_projects:
        write_project_manifest(project)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def project_package_path(name: str) -> Path:
    cleaned = re.sub(r"[/:]", "-", name).strip().strip(".")
    if not cleaned:
        raise ValueError("Enter a project name.")
    return GENERATIONS_DIR / f"{cleaned}.lisproject"


def write_project_manifest(row: sqlite3.Row | dict[str, Any]) -> None:
    package = Path(row["package_path"])
    package.mkdir(parents=True, exist_ok=True)
    (package / "Images").mkdir(exist_ok=True)
    manifest = {
        "format": "Local Image Studio Project",
        "version": 2,
        "id": row["id"],
        "name": row["name"],
        "storage": "Lossless PNG originals; central SQLite metadata",
        "updated_at": row["updated_at"],
    }
    temporary = package / "project.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(package / "project.json")


def public_project(row: sqlite3.Row) -> dict[str, Any]:
    with database() as connection:
        count = connection.execute("SELECT COUNT(*) FROM generations WHERE project_id = ?", (row["id"],)).fetchone()[0]
    return {
        "id": row["id"],
        "name": row["name"],
        "archived": bool(row["archived"]),
        "generation_count": count,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_projects() -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute("SELECT * FROM projects ORDER BY archived, name COLLATE NOCASE").fetchall()
    return [public_project(row) for row in rows]


def project_row(project_id: str) -> sqlite3.Row | None:
    with database() as connection:
        return connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def create_project(name: str) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("Project names must be between 1 and 100 characters.")
    package = project_package_path(name)
    if package.exists():
        raise ValueError("A project package with that name already exists.")
    project_id = str(uuid.uuid4())
    now = iso_now()
    try:
        with database() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, package_path, archived, archive_path, created_at, updated_at) VALUES (?, ?, ?, 0, NULL, ?, ?)",
                (project_id, name, str(package), now, now),
            )
    except sqlite3.IntegrityError:
        raise ValueError("A project with that name already exists.") from None
    row = project_row(project_id)
    assert row
    write_project_manifest(row)
    return public_project(row)


def unique_destination(directory: Path, filename: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem, suffix = Path(filename).stem, Path(filename).suffix
    return directory / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"


def rename_project(project_id: str, name: str) -> dict[str, Any]:
    row = project_row(project_id)
    if not row:
        raise ValueError("Project not found.")
    if row["archived"]:
        raise ValueError("Restore the project before renaming it.")
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("Project names must be between 1 and 100 characters.")
    old_package = Path(row["package_path"])
    new_package = project_package_path(name)
    if new_package != old_package and new_package.exists():
        raise ValueError("A project package with that name already exists.")
    if old_package.exists() and new_package != old_package:
        old_package.rename(new_package)
    now = iso_now()
    with database() as connection:
        existing = connection.execute("SELECT id FROM projects WHERE name = ? COLLATE NOCASE AND id != ?", (name, project_id)).fetchone()
        if existing:
            if new_package.exists() and new_package != old_package:
                new_package.rename(old_package)
            raise ValueError("A project with that name already exists.")
        generations = connection.execute("SELECT id, image_path FROM generations WHERE project_id = ?", (project_id,)).fetchall()
        for generation in generations:
            old_path = Path(generation["image_path"])
            if old_package in old_path.parents:
                relative = old_path.relative_to(old_package)
                new_path = new_package / relative
                connection.execute(
                    "UPDATE generations SET image_path = ? WHERE id = ?",
                    (str(new_path), generation["id"]),
                )
                connection.execute(
                    "UPDATE generations SET reference_image_path = ? WHERE reference_source_id = ?",
                    (str(new_path), generation["id"]),
                )
        connection.execute(
            "UPDATE projects SET name = ?, package_path = ?, updated_at = ? WHERE id = ?",
            (name, str(new_package), now, project_id),
        )
    updated = project_row(project_id)
    assert updated
    write_project_manifest(updated)
    return public_project(updated)


def move_generation(generation_id: str, destination_project_id: str | None) -> dict[str, Any]:
    row = generation_row(generation_id)
    if not row:
        raise ValueError("Generation not found.")
    source = Path(row["image_path"])
    if not source.is_file():
        raise ValueError("Restore the archived project before moving this generation.")
    if destination_project_id:
        project = project_row(destination_project_id)
        if not project:
            raise ValueError("Destination project not found.")
        if project["archived"]:
            raise ValueError("Restore the destination project first.")
        directory = Path(project["package_path"]) / "Images"
        directory.mkdir(parents=True, exist_ok=True)
    else:
        directory = GENERATIONS_DIR
    if row["project_id"] == destination_project_id and source.parent.resolve() == directory.resolve():
        return public_generation(row)
    destination = unique_destination(directory, source.name)
    if source.resolve() != destination.resolve():
        shutil.move(str(source), str(destination))
    with database() as connection:
        connection.execute(
            "UPDATE generations SET project_id = ?, image_path = ? WHERE id = ?",
            (destination_project_id, str(destination), generation_id),
        )
        connection.execute(
            "UPDATE generations SET reference_image_path = ? WHERE reference_source_id = ?",
            (str(destination), generation_id),
        )
        now = iso_now()
        source_project_id = row["project_id"]
        if source_project_id:
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, source_project_id))
        if destination_project_id:
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, destination_project_id))
    for affected_project_id in {row["project_id"], destination_project_id} - {None}:
        affected = project_row(affected_project_id)
        if affected and not affected["archived"]:
            write_project_manifest(affected)
    updated = generation_row(generation_id)
    assert updated
    return public_generation(updated)


def archive_project(project_id: str) -> dict[str, Any]:
    row = project_row(project_id)
    if not row:
        raise ValueError("Project not found.")
    if row["archived"]:
        return public_project(row)
    package = Path(row["package_path"])
    if not package.is_dir():
        raise ValueError("The project package is missing.")
    write_project_manifest(row)
    archive = PROJECT_ARCHIVES_DIR / f"{package.name}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    image_entries: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for item in package.rglob("*"):
                if not item.is_file():
                    continue
                relative = item.relative_to(package)
                arcname = Path(package.name) / relative
                if relative.parts[:1] == ("Images",) and item.suffix.lower() == ".png":
                    stored_name = arcname.with_suffix(".lossless.webp")
                    encoded = io.BytesIO()
                    with Image.open(item) as image:
                        image.load()
                        image.save(encoded, format="WEBP", lossless=True, method=6, exact=True)
                    bundle.writestr(str(stored_name), encoded.getvalue(), compress_type=zipfile.ZIP_STORED)
                    image_entries.append({"stored": str(stored_name), "restore": str(arcname)})
                else:
                    bundle.write(item, arcname=str(arcname))
            archive_manifest = {
                "format": "Local Image Studio Project Archive",
                "version": 1,
                "image_codec": ARCHIVE_IMAGE_CODEC,
                "images": image_entries,
            }
            bundle.writestr(
                str(Path(package.name) / ARCHIVE_MANIFEST_NAME),
                json.dumps(archive_manifest, indent=2),
            )
    except Exception:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise RuntimeError("The project archive could not be created.")
    temporary.replace(archive)
    shutil.rmtree(package)
    now = iso_now()
    with database() as connection:
        connection.execute(
            "UPDATE projects SET archived = 1, archive_path = ?, updated_at = ? WHERE id = ?",
            (str(archive), now, project_id),
        )
    updated = project_row(project_id)
    assert updated
    return public_project(updated)


def restore_project(project_id: str) -> dict[str, Any]:
    row = project_row(project_id)
    if not row:
        raise ValueError("Project not found.")
    if not row["archived"]:
        return public_project(row)
    archive = Path(row["archive_path"] or "")
    package = Path(row["package_path"])
    if not archive.is_file():
        raise ValueError("The project archive is missing.")
    with zipfile.ZipFile(archive, "r") as bundle:
        base = GENERATIONS_DIR.resolve()
        for member in bundle.infolist():
            destination = (GENERATIONS_DIR / member.filename).resolve()
            if base not in destination.parents and destination != base:
                raise RuntimeError("Unsafe project archive path.")
        archive_manifest_name = str(Path(package.name) / ARCHIVE_MANIFEST_NAME)
        if archive_manifest_name in bundle.namelist():
            archive_manifest = json.loads(bundle.read(archive_manifest_name))
            if archive_manifest.get("format") != "Local Image Studio Project Archive":
                raise RuntimeError("The project archive manifest is invalid.")
            image_entries = archive_manifest.get("images")
            if not isinstance(image_entries, list):
                raise RuntimeError("The project archive image map is invalid.")
            stored_images = {entry.get("stored") for entry in image_entries if isinstance(entry, dict)}
            for member in bundle.infolist():
                if member.filename != archive_manifest_name and member.filename not in stored_images:
                    bundle.extract(member, GENERATIONS_DIR)
            for entry in image_entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("stored"), str) or not isinstance(entry.get("restore"), str):
                    raise RuntimeError("The project archive image map is invalid.")
                stored_name = entry["stored"]
                destination = (GENERATIONS_DIR / entry["restore"]).resolve()
                if stored_name not in bundle.namelist() or (base not in destination.parents and destination != base):
                    raise RuntimeError("The project archive image entry is invalid.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(io.BytesIO(bundle.read(stored_name))) as image:
                    image.load()
                    image.save(destination, format="PNG", optimize=True, compress_level=9)
        else:
            bundle.extractall(GENERATIONS_DIR)
    if not package.is_dir():
        raise RuntimeError("The restored project package is invalid.")
    archive.unlink()
    with database() as connection:
        connection.execute(
            "UPDATE projects SET archived = 0, archive_path = NULL, updated_at = ? WHERE id = ?",
            (iso_now(), project_id),
        )
    updated = project_row(project_id)
    assert updated
    write_project_manifest(updated)
    return public_project(updated)


def delete_project(project_id: str) -> None:
    row = project_row(project_id)
    if not row:
        raise ValueError("Project not found.")
    if row["archived"]:
        restore_project(project_id)
        row = project_row(project_id)
        assert row
    with database() as connection:
        generations = connection.execute("SELECT id FROM generations WHERE project_id = ?", (project_id,)).fetchall()
    for generation in generations:
        move_generation(generation["id"], None)
    package = Path(row["package_path"])
    if package.is_dir():
        shutil.rmtree(package)
    with database() as connection:
        connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def generation_row(generation_id: str) -> sqlite3.Row | None:
    with database() as connection:
        return connection.execute("SELECT * FROM generations WHERE id = ?", (generation_id,)).fetchone()


def public_generation(row: sqlite3.Row) -> dict[str, Any]:
    quantization = row["quantization"]
    return {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "project_id": row["project_id"],
        "original_prompt": row["original_prompt"] or row["prompt"],
        "improved_prompt": row["improved_prompt"] or row["prompt"],
        "prompt_improvement_model": row["prompt_improvement_model"],
        "prompt_improvement_strength": row["prompt_improvement_strength"],
        "prompt_helper": {
            "model": row["prompt_improvement_model"],
            "tokens_per_second": row["tokens_per_second"],
            "time_to_first_token": row["time_to_first_token"],
            "token_count": row["token_count"],
            "total_time": row["prompt_helper_time"],
        },
        "model_id": row["model_id"],
        "model": row["model_label"],
        "quantization": quantization,
        "quantization_label": "None" if quantization is None else f"Q{quantization}",
        "seed": row["seed"],
        "width": row["width"],
        "height": row["height"],
        "steps": row["steps"],
        "generation_time": round(row["generation_time"], 3),
        "seconds_per_image": round(row["seconds_per_image"], 3),
        "steps_per_second": round(row["steps_per_second"], 3),
        "peak_memory_bytes": row["peak_memory_bytes"],
        "gpu_utilization": row["gpu_utilization"],
        "reference_used": bool(row["reference_used"]),
        "reference_source_id": row["reference_source_id"],
        "reference_image_path": row["reference_image_path"],
        "lora_name": row["lora_name"],
        "lora_scale": row["lora_scale"],
        "variant_group_id": row["variant_group_id"],
        "variant_index": row["variant_index"],
        "variant_count": row["variant_count"],
        "generation_group_id": row["generation_group_id"],
        "created_at": row["created_at"],
        "image_path": row["image_path"],
        "thumbnail_path": row["thumbnail_path"],
        "filename": Path(row["image_path"]).name,
        "archived": not Path(row["image_path"]).is_file(),
        # Upscale metadata
        "upscale_source_width": row["upscale_source_width"] or 0,
        "upscale_source_height": row["upscale_source_height"] or 0,
        "upscale_scale_factor": row["upscale_scale_factor"] if "upscale_scale_factor" in row.keys() else None,
        "upscale_model_variant": row["upscale_model_variant"] if "upscale_model_variant" in row.keys() else None,
        "upscale_precision": row["upscale_precision"] if "upscale_precision" in row.keys() else None,
    }


def history(limit: int = 500) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)
        ).fetchall()
    return [public_generation(row) for row in rows]


PROMPT_HELPER_SYSTEM = """You improve prompts for an image-generation model. Preserve every explicit constraint, proper name, number, count, and negative requirement exactly. Add useful visual specificity, composition, materials, lighting, camera or art-direction terms only when they support the request. Never creatively replace the user's concept. Never remove technical requirements such as 'exactly eight wheels'. Avoid unnecessary verbosity. Return only the improved prompt, with no preamble or commentary."""


class PromptHelperResult:
    def __init__(self, prompt: str, model: str | None = None, tokens_per_second: float | None = None, ttft: float | None = None, token_count: int | None = None, total_time: float | None = None, notice: str | None = None):
        self.prompt = prompt
        self.model = model
        self.tokens_per_second = tokens_per_second
        self.ttft = ttft
        self.token_count = token_count
        self.total_time = total_time
        self.notice = notice


class PromptHelper:
    def improve(self, prompt: str, strength: str) -> PromptHelperResult:
        raise NotImplementedError


class LMStudioPromptHelper(PromptHelper):
    endpoint = "http://127.0.0.1:1234"

    @staticmethod
    def request(url: str, data: bytes | None = None, timeout: float = 1.0):
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)

    @classmethod
    def available_models(cls) -> list[str]:
        try:
            with cls.request(f"{cls.endpoint}/v1/models", timeout=0.45) as response:
                payload = json.load(response)
            return list(dict.fromkeys(str(item["id"]) for item in payload.get("data", [])
                                      if cls.is_chat_model(item)))
        except Exception:
            return []

    @staticmethod
    def is_chat_model(item: dict[str, Any]) -> bool:
        """Honor explicit type/capabilities; v1 ID-only entries are chat candidates.

        OpenAI's model list does not require capability metadata. Exclude known
        non-chat families and let the existing safe completion fallback handle
        servers that advertise an incompatible model without metadata.
        """
        model = str(item.get("id") or "")
        if not model or re.search(r"flux|seedvr|stable.?diffusion|embedding|embed|whisper|tts|rerank", model, re.I):
            return False
        kind = str(item.get("type") or item.get("model_type") or "").lower()
        if kind and kind not in {"llm", "vlm", "chat", "text", "language", "model"}:
            return False
        capabilities = item.get("capabilities")
        if isinstance(capabilities, list) and capabilities:
            return bool(set(capabilities) & {"chat", "text", "completion", "chat_completion"})
        return True

    @staticmethod
    def choose_model(models: list[str]) -> str | None:
        preferred = [model for model in models if re.search(r"qwen.*3[-_]?4b.*2507", model, re.I)]
        if preferred:
            return preferred[0]
        small = [model for model in models if re.search(r"(?:^|[-_])(4|5|6|7|8)b(?:[-_]|$)", model, re.I) and re.search(r"instruct|qwen|mistral|llama", model, re.I)]
        if small:
            return small[0]
        fallback = [model for model in models if re.search(r"qwen.?3\.6.*35b|qwen.*35b", model, re.I)]
        return fallback[0] if fallback else None

    def improve(self, prompt: str, strength: str, model_id: str | None = None) -> PromptHelperResult:
        if model_id == "off":
            return PromptHelperResult(prompt)
        models = self.available_models()
        model = (model_id if model_id in models else None) if model_id is not None else self.choose_model(models)
        if not model:
            return PromptHelperResult(prompt, notice="Prompt improvement unavailable — original prompt used")
        instruction = {
            "light": "Make only light refinements and stay concise.",
            "normal": "Add a moderate amount of useful visual detail.",
            "strong": "Add strong visual direction while preserving every constraint.",
        }.get(strength, "Add a moderate amount of useful visual detail.")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": PROMPT_HELPER_SYSTEM},
                {"role": "user", "content": f"{instruction}\n\nOriginal prompt:\n{prompt}"},
            ],
            "temperature": 0,
            "max_tokens": 220,
            "stream": False,
        }
        if re.search(r"qwen.?3\.6.*35b|qwen.*35b", model, re.I):
            # This LM Studio MLX model ignores request-level thinking controls.
            # 768 tokens still ended inside reasoning; allow room for the answer.
            # Keep this budget local to the prompt helper, not model settings.
            payload["max_tokens"] = 2048
        started = time.perf_counter()
        try:
            with self.request(
                f"{self.endpoint}/v1/chat/completions",
                json.dumps(payload).encode("utf-8"),
                timeout=45,
            ) as response:
                result = json.load(response)
            total = max(time.perf_counter() - started, 0.001)
            choice = result["choices"][0]
            content = choice["message"].get("content")
            # Never use reasoning as a prompt or accept a truncated answer that
            # may have lost one of the user's constraints. JSON null is not text.
            if not isinstance(content, str) or not content.strip() or choice.get("finish_reason") == "length":
                raise ValueError("Empty, invalid, or truncated helper response")
            improved = content.strip()
            usage = result.get("usage") or {}
            tokens = usage.get("completion_tokens")
            tokens_per_second = (float(tokens) / total) if tokens else None
            return PromptHelperResult(improved, model=model, tokens_per_second=tokens_per_second, token_count=tokens, total_time=total)
        except Exception:
            return PromptHelperResult(prompt, notice="Prompt improvement unavailable — original prompt used")


PROMPT_HELPER = LMStudioPromptHelper()


class PersistentWorker:
    def __init__(self):
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.command_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.status = "unloaded"
        self.model_id: str | None = None
        self.active_memory_bytes: int | None = None

    def public_status(self) -> dict[str, Any]:
        with self.status_lock:
            return {"status": self.status, "model_id": self.model_id, "active_memory_bytes": self.active_memory_bytes}

    def _update_status(self, event: dict[str, Any]) -> None:
        if event.get("event") != "status":
            return
        with self.status_lock:
            self.status = event.get("status", self.status)
            if self.status == "unloaded":
                self.model_id = None
                self.active_memory_bytes = None
            else:
                self.model_id = event.get("model_id", self.model_id)
                self.active_memory_bytes = event.get("active_memory_bytes", self.active_memory_bytes)

    def _reader(self, stream) -> None:
        for line in stream:
            if not line.startswith("LISJSON "):
                continue
            try:
                event = json.loads(line[len("LISJSON ") :])
                self._update_status(event)
                self.events.put(event)
            except json.JSONDecodeError:
                continue

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        if not MFLUX_PYTHON.is_file():
            raise RuntimeError("The existing MFLUX Python runtime could not be found.")
        environment = v1.offline_environment()
        environment["PYTHONUNBUFFERED"] = "1"
        self.process = subprocess.Popen(
            [str(MFLUX_PYTHON), str(WORKER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
            start_new_session=True,
        )
        assert self.process.stdout
        threading.Thread(target=self._reader, args=(self.process.stdout,), daemon=True).start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=0.2)
                if event.get("event") == "ready":
                    return
            except queue.Empty:
                if self.process.poll() is not None:
                    break
        raise RuntimeError("The MFLUX worker could not start.")

    def _write(self, payload: dict[str, Any]) -> None:
        self.start()
        assert self.process and self.process.stdin
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def generate(self, params: dict[str, Any], callback: Callable[[dict[str, Any]], None]) -> tuple[list[dict[str, Any]], int | None]:
        request_id = str(uuid.uuid4())
        with self.command_lock:
            self._write({"action": "generate", "request_id": request_id, "params": params})
            peak_rss: int | None = None
            deadline = time.monotonic() + 3600
            while time.monotonic() < deadline:
                try:
                    event = self.events.get(timeout=0.25)
                except queue.Empty:
                    if self.process:
                        rss = v1.process_rss_bytes(self.process.pid)
                        if rss is not None:
                            peak_rss = max(peak_rss or 0, rss)
                    continue
                if event.get("request_id") not in (None, request_id):
                    continue
                callback(event)
                if event.get("event") == "result":
                    return event["results"], peak_rss
                if event.get("event") == "error":
                    raise RuntimeError(event.get("message") or "MFLUX generation failed.")
            raise RuntimeError("MFLUX generation timed out.")

    def unload(self) -> bool:
        if not self.process or self.process.poll() is not None:
            with self.status_lock:
                self.status, self.model_id, self.active_memory_bytes = "unloaded", None, None
            return True
        request_id = str(uuid.uuid4())
        with self.command_lock:
            self._write({"action": "unload", "request_id": request_id})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    event = self.events.get(timeout=0.25)
                except queue.Empty:
                    continue
                if event.get("request_id") == request_id and event.get("event") == "result":
                    return True
        return False

    def shutdown(self) -> None:
        process = self.process
        if not process:
            return
        if process.poll() is None:
            request_id = str(uuid.uuid4())
            with contextlib.suppress(Exception):
                assert process.stdin
                process.stdin.write(json.dumps({"action": "shutdown", "request_id": request_id}) + "\n")
                process.stdin.flush()
                process.wait(timeout=10)
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
        self.process = None
        with self.status_lock:
            self.status, self.model_id, self.active_memory_bytes = "unloaded", None, None


WORKER = PersistentWorker()


def cancel_idle_timer() -> None:
    global IDLE_TIMER
    if IDLE_TIMER:
        IDLE_TIMER.cancel()
        IDLE_TIMER = None


# SeedVR2 7B upscaler management
SEEDVR2_MODEL_ID = "seedvr2_7b"
SEEDVR2_TRANSFORMER_FILE = "seedvr2_ema_7b_fp16.safetensors"
SEEDVR2_VAE_FILE = "ema_vae_fp16.safetensors"
SEEDVR2_REPO_ID = "numz/SeedVR2_comfyUI"

# SeedVR2 installation state (background job)
_SEEDVR2_INSTALL_LOCK = threading.Lock()
_SEEDVR2_INSTALLING: bool = False
_SEEDVR2_INSTALL_ERROR: str | None = None


def seedvr2_is_installed() -> bool:
    """Check whether SeedVR2 7B model files exist in the cache."""
    return v1.model_is_installed(SEEDVR2_MODEL_ID)


def seedvr2_install_status() -> dict[str, Any]:
    """Return installation status for the Models UI."""
    installed = seedvr2_is_installed()
    with _SEEDVR2_INSTALL_LOCK:
        installing = _SEEDVR2_INSTALLING
        error = _SEEDVR2_INSTALL_ERROR
    return {
        "installed": installed,
        "installing": installing,
        "error": error,
        "approx_size_mb": 14000,
    }


def _install_seedvr2_background() -> None:
    """Download SeedVR2 7B FP16 checkpoint + VAE in a background thread."""
    global _SEEDVR2_INSTALLING, _SEEDVR2_INSTALL_ERROR
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        with _SEEDVR2_INSTALL_LOCK:
            _SEEDVR2_INSTALL_ERROR = "huggingface_hub is not installed in the MFLUX runtime."
        return
    try:
        cache_path = v1.model_cache_path(SEEDVR2_MODEL_ID)
        snapshot_download(
            repo_id=SEEDVR2_REPO_ID,
            allow_patterns=[SEEDVR2_TRANSFORMER_FILE, SEEDVR2_VAE_FILE],
            local_dir=cache_path.parent,
            local_dir_use_symlinks=False,
        )
    except Exception as error:
        with _SEEDVR2_INSTALL_LOCK:
            _SEEDVR2_INSTALL_ERROR = str(error)
    else:
        with _SEEDVR2_INSTALL_LOCK:
            if not seedvr2_is_installed():
                _SEEDVR2_INSTALL_ERROR = "Download completed but required model files not found in cache."
            else:
                _SEEDVR2_INSTALL_ERROR = None  # success
    finally:
        with _SEEDVR2_INSTALL_LOCK:
            _SEEDVR2_INSTALLING = False


def start_upscale(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a SeedVR2 7B upscale job."""
    # Validate inputs
    source_id = str(payload.get("source_generation_id", "")).strip()
    if not source_id:
        raise ValueError("A source generation ID is required.")
    source_row = generation_row(source_id)
    if not source_row:
        raise ValueError("Source generation not found.")
    source_path = str(source_row["image_path"])
    if not Path(source_path).is_file():
        raise ValueError("Source image is missing.")

    project_id = str(payload.get("project_id") or "") or None
    if project_id:
        proj = project_row(project_id)
        if not proj or proj["archived"]:
            raise ValueError("Destination project not found or archived.")

    scale = str(payload.get("scale", "2x")).strip().lower()
    if scale not in ("2x", "4x"):
        raise ValueError("Scale must be '2x' or '4x'.")
    resolution = scale  # SeedVR2 accepts "2x", "4x" directly

    softness = float(payload.get("softness", 0.5))
    if not (0.0 <= softness <= 1.0):
        raise ValueError("Softness must be between 0.0 and 1.0.")

    quantization = payload.get("quantization")  # None, 4, 6, or 8
    if quantization is not None and quantization not in (4, 6, 8):
        raise ValueError("Quantization must be None, 4, 6, or 8.")

    seed = int(payload.get("seed", 42))

    # Check that SeedVR2 is installed (do NOT auto-download)
    if not seedvr2_is_installed():
        raise ValueError(
            "SeedVR2 7B model is not installed. Open the Models view and install it first."
        )

    # Create output paths
    output_directory = generation_output_directory(project_id)
    job_id = str(uuid.uuid4())
    output_path = output_directory / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_upscale_{job_id[:8]}.png"
    thumbnail_path = THUMBNAILS_DIR / f"{job_id}.jpg"

    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "state": "queued",
            "phase": "queued",
            "message": "Preparing upscale…",
            "created_at": iso_now(),
            "model_status": WORKER.public_status(),
            # Upscale-specific fields
            "source_generation_id": source_id,
            "source_image_path": source_path,
            "scale": scale,
            "resolution": resolution,
            "softness": softness,
            "quantization": quantization,
            "seed": seed,
            "project_id": project_id,
            "output_path": str(output_path),
            "thumbnail_path": str(thumbnail_path),
        }
    threading.Thread(target=_run_upscale, args=(job_id,), daemon=True).start()
    return JOBS[job_id].copy()


def _run_upscale(job_id: str) -> None:
    """Run a SeedVR2 7B upscale in the worker."""
    global ACTIVE_JOB_ID
    try:
        with JOBS_LOCK:
            job = JOBS[job_id].copy()
        source_path = Path(job["source_image_path"])
        output_path = Path(job["output_path"])
        thumbnail_path = Path(job["thumbnail_path"])
        scale = job["scale"]
        resolution = job["resolution"]
        softness = float(job["softness"])
        quantization = job.get("quantization")
        seed = int(job["seed"])
        project_id = job.get("project_id")

        with JOBS_LOCK:
            JOBS[job_id].update({"state": "running", "phase": "loading", "message": f"Loading SeedVR2 7B…"})

        params = {
            "output_path": str(output_path),
            "image_path": str(source_path),
            "resolution": resolution,
            "softness": softness,
            "quantization": quantization,
            "seed": seed,
        }

        request_id = str(uuid.uuid4())
        with WORKER.command_lock:
            WORKER._write({"action": "upscale", "request_id": request_id, "params": params})
            peak_rss: int | None = None
            deadline = time.monotonic() + 600  # 10 min max
            results: list[dict[str, Any]] = []
            while time.monotonic() < deadline:
                try:
                    event = WORKER.events.get(timeout=0.25)
                except queue.Empty:
                    if WORKER.process and WORKER.process.poll() is None:
                        rss = v1.process_rss_bytes(WORKER.process.pid)
                        if rss is not None:
                            peak_rss = max(peak_rss or 0, rss)
                    continue
                if event.get("request_id") != request_id:
                    continue
                # Update job with status events
                if event.get("event") == "status":
                    status = event.get("status", "")
                    if status == "loading":
                        with JOBS_LOCK:
                            JOBS[job_id].update({"phase": "loading", "message": f"Loading SeedVR2 7B…", "model_status": WORKER.public_status()})
                    elif status == "loaded":
                        load_secs = event.get("load_seconds", 0)
                        with JOBS_LOCK:
                            JOBS[job_id].update({"phase": "upscaling", "message": f"Upscaling · SeedVR2 7B · {scale} · {load_secs:.1f}s load", "model_status": WORKER.public_status()})
                elif event.get("event") == "result":
                    results.append(event)
                    break
                elif event.get("event") == "error":
                    raise RuntimeError(event.get("message", "Upscale failed"))

        if not results:
            raise RuntimeError("Upscale timed out.")

        result = results[0]
        output_file = Path(result["output_path"])

        # Create thumbnail
        try:
            v1.create_thumbnail(str(output_file), str(thumbnail_path))
        except Exception:
            pass  # Non-critical

        elapsed = max(float(result.get("generation_time", 0)), 0.001)
        peak_memory = max(
            (result.get("peak_memory_bytes"), peak_rss),
            key=lambda x: x or 0,
        ) if any(v is not None for v in (result.get("peak_memory_bytes"), peak_rss)) else None

        # Get source dimensions for metadata
        source_row = generation_row(job["source_generation_id"])
        src_width = source_row["width"] if source_row else 0
        src_height = source_row["height"] if source_row else 0
        try:
            with Image.open(str(output_file)) as img:
                out_width, out_height = img.size
        except Exception:
            out_width = src_width * (2 if scale == "2x" else 4)
            out_height = src_height * (2 if scale == "2x" else 4)

        # Save to database with upscale metadata
        generation_id = str(uuid.uuid4())
        now = iso_now()
        with database() as connection:
            connection.execute(
                """
                INSERT INTO generations (
                    id, image_path, thumbnail_path, prompt, model_id, model_label,
                    quantization, seed, width, height, steps, generation_time,
                    seconds_per_image, steps_per_second, peak_memory_bytes,
                    created_at, parent_id, project_id, original_prompt,
                    upscale_source_width, upscale_source_height,
                    upscale_scale_factor, upscale_model_variant,
                    upscale_precision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id, str(output_file), str(thumbnail_path),
                    f"Upscale {scale} — SeedVR2 7B",
                    SEEDVR2_MODEL_ID,
                    "SeedVR2 7B",
                    quantization,
                    seed,
                    out_width, out_height, 1, elapsed,
                    elapsed, 1.0 / max(elapsed, 0.001),
                    peak_memory,
                    now,
                    job["source_generation_id"],
                    project_id,
                    f"Upscale {scale} from source",
                    src_width, src_height,
                    scale.replace("x", "×"),
                    "7B",
                    "FP16",
                ),
            )

        with JOBS_LOCK:
            updated = generation_row(generation_id)
            assert updated
            pub_result = public_generation(updated)
            JOBS[job_id].update(
                {
                    "state": "complete",
                    "phase": "complete",
                    "message": f"SeedVR2 7B · {src_width}×{src_height} → {out_width}×{out_height} · {elapsed:.1f}s",
                    "generation": pub_result,
                    "model_status": WORKER.public_status(),
                }
            )
        schedule_retention("automatic")
    except Exception as error:
        with contextlib.suppress(OSError):
            Path(job.get("output_path", "")).unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            Path(job.get("thumbnail_path", "")).unlink(missing_ok=True)
        with JOBS_LOCK:
            JOBS[job_id].update({"state": "error", "phase": "error", "message": str(error)})
        schedule_retention("automatic")
    finally:
        with JOBS_LOCK:
            ACTIVE_JOB_ID = None


def schedule_retention(mode: str) -> None:
    global IDLE_TIMER
    cancel_idle_timer()
    if mode == "immediate":
        threading.Thread(target=WORKER.unload, daemon=True).start()
    elif mode == "automatic":
        IDLE_TIMER = threading.Timer(RETENTION_SECONDS, WORKER.unload)
        IDLE_TIMER.daemon = True
        IDLE_TIMER.start()


def validate_v2_payload(payload: dict[str, Any]) -> dict[str, Any]:
    config = v1.validate_generation_payload(payload)
    variant_count = v1.validate_integer(payload.get("variant_count", 1), "Variant count", 1, 4)
    if variant_count not in (1, 2, 4):
        raise ValueError("Variant count must be 1, 2, or 4.")
    parent_id = payload.get("parent_id") or None
    if parent_id and not generation_row(str(parent_id)):
        raise ValueError("The fork parent no longer exists.")
    project_id = payload.get("project_id") or None
    if project_id:
        project = project_row(str(project_id))
        if not project:
            raise ValueError("Project not found.")
        if project["archived"]:
            raise ValueError("Restore the project before generating into it.")
    strength = str(payload.get("prompt_improvement_strength", "normal")).lower()
    if strength not in {"light", "normal", "strong"}:
        strength = "normal"
    retention = str(payload.get("model_retention", "automatic"))
    if retention not in {"automatic", "keep", "immediate"}:
        retention = "automatic"
    persistent_reference: str | None = None
    if payload.get("reference_path"):
        candidate = Path(str(payload["reference_path"])).expanduser().resolve()
        references_root = REFERENCES_DIR.resolve()
        if references_root not in candidate.parents or not candidate.is_file():
            raise ValueError("The saved reference image is unavailable.")
        if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("The saved reference image format is unsupported.")
        persistent_reference = str(candidate)
    config.update(
        {
            "variant_count": variant_count,
            "parent_id": parent_id,
            "project_id": project_id,
            "prompt_improvement": bool(payload.get("prompt_improvement", True)),
            "prompt_improvement_strength": strength,
            "prompt_helper_model": str(payload["prompt_helper_model"]) if payload.get("prompt_helper_model") is not None else None,
            "improved_prompt_override": str(payload.get("improved_prompt_override") or "").strip() or None,
            "model_retention": retention,
            "reference_path": persistent_reference,
        }
    )
    return config


def generation_output_directory(project_id: str | None) -> Path:
    if not project_id:
        return GENERATIONS_DIR
    project = project_row(project_id)
    if not project:
        raise ValueError("Project not found.")
    directory = Path(project["package_path"]) / "Images"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def worker_event_to_job(job_id: str, event: dict[str, Any]) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        if event.get("event") == "status":
            status = event.get("status")
            model_id = event.get("model_id")
            if model_id == "seedvr2_7b":
                short = "SeedVR2 7B"
            else:
                short = "9B" if model_id == "flux2_klein_9b" else "4B"
            if status == "loading":
                job.update({"phase": "loading", "message": f"Loading {short}…", "model_status": WORKER.public_status()})
            elif status == "loaded":
                job.update({"phase": "upscaling" if model_id == "seedvr2_7b" else "generating", "message": "Upscaling…" if model_id == "seedvr2_7b" else "Generating", "model_status": WORKER.public_status()})
            elif status == "unloaded":
                job.update({"model_status": WORKER.public_status()})
        elif event.get("event") == "progress":
            step = event.get("step", 0)
            steps = event.get("steps")
            variant_index = event.get("variant_index", 1)
            variant_count = event.get("variant_count", 1)
            message = f"Generating · Step {step}/{steps}" if steps else "Generating"
            if variant_count > 1:
                message += f" · Variant {variant_index}/{variant_count}"
            job.update(
                {
                    "phase": "generating",
                    "message": message,
                    "step": step,
                    "steps": steps,
                    "variant_index": variant_index,
                    "variant_count": variant_count,
                    "elapsed": event.get("elapsed"),
                    "peak_memory_bytes": event.get("peak_memory_bytes"),
                    "model_status": WORKER.public_status(),
                }
            )


def run_generation(job_id: str, config: dict[str, Any]) -> None:
    global ACTIVE_JOB_ID
    reference_path: Path | None = None
    delete_reference = False
    created_paths: list[Path] = []
    created_thumbnails: list[Path] = []
    try:
        original_prompt = config["prompt"]
        with JOBS_LOCK:
            JOBS[job_id].update({"state": "running", "phase": "prompt", "message": "Improving prompt…" if config["prompt_improvement"] else "Preparing generation…"})
        if config["improved_prompt_override"]:
            helper = PromptHelperResult(config["improved_prompt_override"], model="Edited by user")
        elif config["prompt_improvement"]:
            if config.get("prompt_helper_model") is not None:
                helper = PROMPT_HELPER.improve(original_prompt, config["prompt_improvement_strength"], model_id=config["prompt_helper_model"])
            else:
                helper = PROMPT_HELPER.improve(original_prompt, config["prompt_improvement_strength"])
        else:
            helper = PromptHelperResult(original_prompt)
        improved_prompt = helper.prompt
        with JOBS_LOCK:
            JOBS[job_id].update(
                {
                    "original_prompt": original_prompt,
                    "improved_prompt": improved_prompt,
                    "prompt_notice": helper.notice,
                    "prompt_helper": {
                        "model": helper.model,
                        "tokens_per_second": helper.tokens_per_second,
                        "time_to_first_token": helper.ttft,
                        "token_count": helper.token_count,
                        "total_time": helper.total_time,
                    },
                }
            )
        if config["reference_path"]:
            reference_path = Path(config["reference_path"])
            delete_reference = False
        else:
            reference_path, delete_reference = v1.resolve_reference(config, job_id)
        if reference_path:
            reference_path = reference_path.resolve()
        output_directory = generation_output_directory(config["project_id"])
        variant_group_id = str(uuid.uuid4())
        generation_group_id = str(uuid.uuid4())
        generation_ids = [str(uuid.uuid4()) for _ in range(config["variant_count"])]
        seeds = [config["seed"] + index for index in range(config["variant_count"])]
        outputs = [
            output_directory / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{generation_id[:8]}.png"
            for generation_id in generation_ids
        ]
        thumbnails = [THUMBNAILS_DIR / f"{generation_id}.jpg" for generation_id in generation_ids]
        created_paths.extend(outputs)
        created_thumbnails.extend(thumbnails)

        if os.environ.get("LIS_TEST_MODE") == "1":
            results = []
            for output, seed in zip(outputs, seeds, strict=True):
                v1.fake_test_image(output)
                results.append({"output": str(output), "seed": seed, "generation_time": 0.05, "peak_memory_bytes": v1.process_rss_bytes(os.getpid())})
            peak_rss = v1.process_rss_bytes(os.getpid())
        else:
            params = {
                "model_id": config["model_id"],
                "quantization": config["quantization"],
                "prompt": improved_prompt,
                "width": config["width"],
                "height": config["height"],
                "steps": config["steps"],
                "outputs": [str(path) for path in outputs],
                "seeds": seeds,
                "reference_paths": [str(reference_path)] if reference_path else [],
                "lora_paths": [str(config["lora_path"])] if config["lora_path"] else [],
                "lora_scales": [config["lora_scale"]] if config["lora_path"] else [],
            }
            cancel_idle_timer()
            results, peak_rss = WORKER.generate(params, lambda event: worker_event_to_job(job_id, event))

        model = v1.MODEL_DEFINITIONS[config["model_id"]]
        public_results = []
        for index, (generation_id, output, thumbnail, result) in enumerate(
            zip(generation_ids, outputs, thumbnails, results, strict=True), start=1
        ):
            v1.create_thumbnail(output, thumbnail)
            elapsed = max(float(result["generation_time"]), 0.001)
            peak_memory = max(value for value in (result.get("peak_memory_bytes"), peak_rss) if value is not None) if any(value is not None for value in (result.get("peak_memory_bytes"), peak_rss)) else None
            with database() as connection:
                connection.execute(
                    """
                    INSERT INTO generations (
                        id, image_path, thumbnail_path, prompt, model_id, model_label, quantization,
                        seed, width, height, steps, generation_time, seconds_per_image,
                        steps_per_second, peak_memory_bytes, gpu_utilization, tokens_per_second,
                        time_to_first_token, token_count, reference_used, lora_name, lora_scale,
                        created_at, parent_id, project_id, original_prompt, improved_prompt,
                        prompt_improvement_model, prompt_improvement_strength, prompt_helper_time,
                        reference_source_id, reference_image_path, variant_group_id, variant_index,
                        variant_count, generation_group_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id, str(output), str(thumbnail), improved_prompt, config["model_id"], model["label"],
                        config["quantization"], result["seed"], config["width"], config["height"], config["steps"],
                        elapsed, elapsed, config["steps"] / elapsed, peak_memory,
                        helper.tokens_per_second, helper.ttft, helper.token_count, int(reference_path is not None),
                        config["lora_name"], config["lora_scale"] if config["lora_path"] else None, iso_now(),
                        config["parent_id"], config["project_id"], original_prompt, improved_prompt, helper.model,
                        config["prompt_improvement_strength"] if config["prompt_improvement"] else None,
                        helper.total_time, config.get("reference_generation_id"), str(reference_path) if reference_path else None,
                        variant_group_id, index, config["variant_count"], generation_group_id,
                    ),
                )
            row = generation_row(generation_id)
            assert row
            public_results.append(public_generation(row))
        with JOBS_LOCK:
            JOBS[job_id].update(
                {
                    "state": "complete",
                    "phase": "complete",
                    "message": "Generation complete",
                    "generations": public_results,
                    "generation": public_results[0],
                    "model_status": WORKER.public_status(),
                }
            )
        # v2 retains user-supplied references so forks can reuse the same local
        # file without another copy. Failed jobs still clean up their upload.
        delete_reference = False
        schedule_retention(config["model_retention"])
    except Exception as error:
        for path in created_paths + created_thumbnails:
            with contextlib.suppress(OSError):
                path.unlink()
        with JOBS_LOCK:
            JOBS[job_id].update({"state": "error", "phase": "error", "message": str(error)})
        schedule_retention(config.get("model_retention", "automatic"))
    finally:
        if delete_reference and reference_path:
            with contextlib.suppress(OSError):
                reference_path.unlink()
        with JOBS_LOCK:
            ACTIVE_JOB_ID = None


def start_generation(payload: dict[str, Any]) -> dict[str, Any]:
    global ACTIVE_JOB_ID
    config = validate_v2_payload(payload)
    with JOBS_LOCK:
        if ACTIVE_JOB_ID and JOBS.get(ACTIVE_JOB_ID, {}).get("state") in {"queued", "running"}:
            raise RuntimeError("A generation is already running.")
        job_id = str(uuid.uuid4())
        JOBS[job_id] = {
            "id": job_id,
            "state": "queued",
            "phase": "queued",
            "message": "Preparing…",
            "created_at": iso_now(),
            "model_status": WORKER.public_status(),
        }
        ACTIVE_JOB_ID = job_id
    threading.Thread(target=run_generation, args=(job_id, config), daemon=True).start()
    return JOBS[job_id].copy()


def delete_generation(generation_id: str) -> bool:
    row = generation_row(generation_id)
    if not row:
        return False
    with database() as connection:
        children = connection.execute("SELECT id FROM generations WHERE parent_id = ?", (generation_id,)).fetchall()
        for child in children:
            connection.execute("UPDATE generations SET parent_id = ? WHERE id = ?", (row["parent_id"], child["id"]))
        connection.execute(
            "UPDATE generations SET reference_source_id = NULL, reference_image_path = NULL WHERE reference_source_id = ?",
            (generation_id,),
        )
        connection.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
        saved_reference = row["reference_image_path"] if not row["reference_source_id"] else None
        reference_in_use = connection.execute(
            "SELECT 1 FROM generations WHERE reference_image_path = ? LIMIT 1", (saved_reference,)
        ).fetchone() if saved_reference else None
    for key in ("image_path", "thumbnail_path"):
        if row[key]:
            with contextlib.suppress(OSError):
                Path(row[key]).unlink()
    if saved_reference and not reference_in_use:
        reference = Path(saved_reference).resolve()
        if REFERENCES_DIR.resolve() in reference.parents:
            with contextlib.suppress(OSError):
                reference.unlink()
    return True


def active_job() -> dict[str, Any] | None:
    with JOBS_LOCK:
        return JOBS.get(ACTIVE_JOB_ID, {}).copy() if ACTIVE_JOB_ID else None


class V2Handler(BaseHTTPRequestHandler):
    server_version = "LocalImageStudio/2.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        if os.environ.get("LIS_DEBUG") == "1":
            super().log_message(format_string, *args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def authorized(self) -> bool:
        supplied = self.headers.get("X-Local-Image-Studio-Token", "")
        return bool(supplied and secrets.compare_digest(supplied, self.server.session_token))

    def require_auth(self) -> bool:
        if not self.authorized():
            self.send_json({"error": "Unauthorized local request."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request size.") from None
        if length < 0 or length > v1.MAX_JSON_BYTES:
            raise ValueError("Invalid request size.")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Invalid JSON request.") from None
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")
        return value

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self.send_json({"ok": True, "version": 2})
            return
        if path == "/api/models/seedvr2_7b/status":
            self.send_json(seedvr2_install_status())
            return
        if not self.require_auth():
            return
        if path == "/api/bootstrap":
            helper_models = LMStudioPromptHelper.available_models()
            helper_model = LMStudioPromptHelper.choose_model(helper_models)
            self.send_json(
                {
                    "models": [dict(model, purpose="upscale" if model["id"] == SEEDVR2_MODEL_ID else "generation") for model in v1.public_models()],
                    "generations": history(),
                    "projects": list_projects(),
                    "loras": v1.scan_loras(),
                    "active_job": active_job(),
                    "model_status": WORKER.public_status(),
                    "prompt_helper": {
                        "available": helper_model is not None,
                        "models": helper_models,
                        "model": helper_model,
                        "notice": None if helper_model else "Prompt improvement unavailable — original prompt used",
                    },
                    "storage": {"format": "Lossless PNG", "archive": f"{ARCHIVE_IMAGE_CODEC} inside ZIP; metadata uses Deflate level 9"},
                }
            )
            return
        if path == "/api/status":
            self.send_json({"active_job": active_job(), "model_status": WORKER.public_status()})
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                result = job.copy() if job else None
            if result:
                self.send_json(result)
            else:
                self.send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
            return
        self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.require_auth():
            return
        path = self.path.split("?", 1)[0]
        try:
            payload = self.read_json()
            if path == "/api/models/seedvr2_7b/install":
                with _SEEDVR2_INSTALL_LOCK:
                    if seedvr2_is_installed():
                        self.send_json({"ok": True, "message": "SeedVR2 7B is already installed."})
                        return
                    if _SEEDVR2_INSTALLING:
                        self.send_json({"error": "Installation already in progress."}, HTTPStatus.CONFLICT)
                        return
                    _SEEDVR2_INSTALLING = True
                    _SEEDVR2_INSTALL_ERROR = None
                threading.Thread(target=_install_seedvr2_background, daemon=True).start()
                self.send_json({"ok": True, "message": "SeedVR2 7B installation started in background."})
                return
            if path == "/api/generate":
                self.send_json(start_generation(payload), HTTPStatus.ACCEPTED)
                return
            if path == "/api/model/unload":
                if active_job():
                    raise RuntimeError("The model cannot unload during a generation.")
                cancel_idle_timer()
                self.send_json({"ok": WORKER.unload(), "model_status": WORKER.public_status()})
                return
            if path == "/api/shutdown":
                SHUTTING_DOWN.set()
                cancel_idle_timer()
                WORKER.shutdown()
                self.send_json({"ok": True})
                if SERVER:
                    threading.Thread(target=SERVER.shutdown, daemon=True).start()
                return
            if path == "/api/projects":
                self.send_json(create_project(str(payload.get("name", ""))), HTTPStatus.CREATED)
                return
            match = re.fullmatch(r"/api/projects/([0-9a-f-]+)/(rename|archive|restore|reveal)", path)
            if match:
                project_id, action = match.groups()
                if action == "rename":
                    self.send_json(rename_project(project_id, str(payload.get("name", ""))))
                elif action == "archive":
                    self.send_json(archive_project(project_id))
                elif action == "restore":
                    self.send_json(restore_project(project_id))
                else:
                    row = project_row(project_id)
                    if not row:
                        raise ValueError("Project not found.")
                    reveal = row["archive_path"] if row["archived"] else row["package_path"]
                    subprocess.Popen(["/usr/bin/open", "-R", reveal])
                    self.send_json({"ok": True})
                return
            match = re.fullmatch(r"/api/generations/([0-9a-f-]+)/(move|reveal)", path)
            if match:
                generation_id, action = match.groups()
                if action == "move":
                    self.send_json(move_generation(generation_id, payload.get("project_id") or None))
                else:
                    row = generation_row(generation_id)
                    if not row:
                        raise ValueError("Generation not found.")
                    if not Path(row["image_path"]).is_file():
                        raise ValueError("Restore the archived project to reveal this image.")
                    subprocess.Popen(["/usr/bin/open", "-R", row["image_path"]])
                    self.send_json({"ok": True})
                return
            match = re.fullmatch(r"/api/models/([a-z0-9_]+)/reveal", path)
            if match:
                model_id = match.group(1)
                if model_id not in v1.MODEL_DEFINITIONS or not v1.model_cache_path(model_id).exists():
                    raise ValueError("Installed model not found.")
                subprocess.Popen(["/usr/bin/open", str(v1.model_cache_path(model_id))])
                self.send_json({"ok": True})
                return
            if path == "/api/loras/reveal":
                subprocess.Popen(["/usr/bin/open", str(LORAS_DIR)])
                self.send_json({"ok": True})
                return
            if path == "/api/upscale":
                self.send_json(start_upscale(payload), HTTPStatus.ACCEPTED)
                return
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, HTTPStatus.CONFLICT)

    def do_DELETE(self) -> None:
        if not self.require_auth():
            return
        path = self.path.split("?", 1)[0]
        try:
            match = re.fullmatch(r"/api/generations/([0-9a-f-]+)", path)
            if match:
                if delete_generation(match.group(1)):
                    self.send_json({"ok": True})
                else:
                    self.send_json({"error": "Generation not found."}, HTTPStatus.NOT_FOUND)
                return
            match = re.fullmatch(r"/api/projects/([0-9a-f-]+)", path)
            if match:
                delete_project(match.group(1))
                self.send_json({"ok": True})
                return
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)


class V2Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], session_token: str):
        self.session_token = session_token
        super().__init__(address, V2Handler)


def signal_shutdown(_signum: int, _frame: Any) -> None:
    SHUTTING_DOWN.set()
    cancel_idle_timer()
    WORKER.shutdown()
    if SERVER:
        threading.Thread(target=SERVER.shutdown, daemon=True).start()


def main() -> int:
    global SERVER
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v2")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=None)
    arguments = parser.parse_args()
    ensure_directories()
    initialize_database()
    token = arguments.token or secrets.token_urlsafe(32)
    signal.signal(signal.SIGTERM, signal_shutdown)
    signal.signal(signal.SIGINT, signal_shutdown)
    SERVER = V2Server(("127.0.0.1", arguments.port), token)
    print(f"READY {SERVER.server_address[1]} {token}", flush=True)
    try:
        SERVER.serve_forever(poll_interval=0.2)
    finally:
        SHUTTING_DOWN.set()
        cancel_idle_timer()
        WORKER.shutdown()
        SERVER.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
