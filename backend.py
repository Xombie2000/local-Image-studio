#!/usr/bin/env python3
"""Local Image Studio backend.

Small, dependency-free HTTP API around the user's existing MFLUX installation.
It deliberately runs MFLUX in a child process with Hugging Face offline mode set,
so a generation can never trigger a model download.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import http.cookies
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_NAME = "Local Image Studio"
HOME = Path.home()
SOURCE_DIR = Path(__file__).resolve().parent
WEB_DIR = SOURCE_DIR / "web"

APP_SUPPORT = Path(os.environ.get("LIS_APP_SUPPORT", HOME / "Library/Application Support" / APP_NAME))
GENERATIONS_DIR = Path(os.environ.get("LIS_GENERATIONS_DIR", HOME / "Pictures" / APP_NAME))
THUMBNAILS_DIR = APP_SUPPORT / "Thumbnails"
REFERENCES_DIR = APP_SUPPORT / "References"
LORAS_DIR = APP_SUPPORT / "LoRAs"
DATABASE_PATH = APP_SUPPORT / "history.sqlite3"

HF_HUB = Path(os.environ.get("HF_HUB_CACHE", HOME / ".cache/huggingface/hub"))
MFLUX_BIN_DIR = HOME / ".local/bin"
GENERATE_BIN = Path(os.environ.get("LIS_GENERATE_BIN", MFLUX_BIN_DIR / "mflux-generate-flux2"))
EDIT_BIN = Path(os.environ.get("LIS_EDIT_BIN", MFLUX_BIN_DIR / "mflux-generate-flux2-edit"))

MODEL_DEFINITIONS: dict[str, dict[str, str]] = {
    "flux2_klein_4b": {
        "label": "FLUX.2 Klein 4B",
        "tagline": "Fast",
        "mflux_name": "flux2-klein-4b",
        "cache_name": "models--black-forest-labs--FLUX.2-klein-4B",
        "approx_size": "15 GB",
    },
    "flux2_klein_9b": {
        "label": "FLUX.2 Klein 9B",
        "tagline": "Quality",
        "mflux_name": "flux2-klein-9b",
        "cache_name": "models--black-forest-labs--FLUX.2-klein-9B",
        "approx_size": "32 GB",
    },
    "seedvr2_7b": {
        "label": "SeedVR2 7B",
        "tagline": "Upscale",
        "mflux_name": "seedvr2-7b",
        "cache_name": "models--numz--SeedVR2_comfyUI",
        "approx_size": "14 GB",
    },
}

ALLOWED_QUANTIZATION = {None, 4, 6, 8}
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_JSON_BYTES = 40 * 1024 * 1024
MAX_REFERENCE_BYTES = 30 * 1024 * 1024

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
ACTIVE_JOB_ID: str | None = None
ACTIVE_PROCESS: subprocess.Popen[Any] | None = None
SHUTTING_DOWN = threading.Event()
SERVER: ThreadingHTTPServer | None = None


def ensure_directories() -> None:
    for directory in (APP_SUPPORT, GENERATIONS_DIR, THUMBNAILS_DIR, REFERENCES_DIR, LORAS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def database():
    connection = sqlite3.connect(DATABASE_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id TEXT PRIMARY KEY,
                image_path TEXT NOT NULL,
                thumbnail_path TEXT,
                prompt TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_label TEXT NOT NULL,
                quantization INTEGER,
                seed INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                steps INTEGER NOT NULL,
                generation_time REAL NOT NULL,
                seconds_per_image REAL NOT NULL,
                steps_per_second REAL NOT NULL,
                peak_memory_bytes INTEGER,
                gpu_utilization REAL,
                tokens_per_second REAL,
                time_to_first_token REAL,
                token_count INTEGER,
                reference_used INTEGER NOT NULL DEFAULT 0,
                lora_name TEXT,
                lora_scale REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS generations_created_at_idx
                ON generations(created_at DESC);
            """
        )


def model_cache_path(model_id: str) -> Path:
    return HF_HUB / MODEL_DEFINITIONS[model_id]["cache_name"]


def model_is_installed(model_id: str) -> bool:
    cache = model_cache_path(model_id)
    refs_main = cache / "refs/main"
    try:
        revision = refs_main.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    snapshot = cache / "snapshots" / revision
    if model_id == "seedvr2_7b":
        required = (
            snapshot / "seedvr2_ema_7b_fp16.safetensors",
            snapshot / "ema_vae_fp16.safetensors",
        )
        return snapshot.is_dir() and all(path.exists() for path in required)
    required = (
        snapshot / "transformer/config.json",
        snapshot / "text_encoder/config.json",
        snapshot / "vae/config.json",
    )
    return snapshot.is_dir() and all(path.exists() for path in required)


def public_models() -> list[dict[str, Any]]:
    models = []
    for model_id, definition in MODEL_DEFINITIONS.items():
        models.append(
            {
                "id": model_id,
                "label": definition["label"],
                "tagline": definition["tagline"],
                "status": "Installed" if model_is_installed(model_id) else "Not Installed",
                "approx_size": definition["approx_size"],
            }
        )
    return models


def scan_loras() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in sorted(LORAS_DIR.glob("*.safetensors"), key=lambda item: item.name.lower()):
        digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        items.append({"id": digest, "name": path.stem})
    return items


def resolve_lora(lora_id: str | None) -> tuple[Path | None, str | None]:
    if not lora_id:
        return None, None
    for path in LORAS_DIR.glob("*.safetensors"):
        digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        if secrets.compare_digest(digest, lora_id):
            return path.resolve(), path.stem
    raise ValueError("The selected LoRA is no longer available.")


def row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    quantization = row["quantization"]
    return {
        "id": row["id"],
        "prompt": row["prompt"],
        "model_id": row["model_id"],
        "model": row["model_label"],
        "quantization": quantization,
        "quantization_label": "None" if quantization is None else f"Q{quantization}",
        "seed": row["seed"],
        "width": row["width"],
        "height": row["height"],
        "steps": row["steps"],
        "generation_time": round(row["generation_time"], 2),
        "seconds_per_image": round(row["seconds_per_image"], 2),
        "steps_per_second": round(row["steps_per_second"], 3),
        "peak_memory_bytes": row["peak_memory_bytes"],
        "gpu_utilization": row["gpu_utilization"],
        "tokens_per_second": row["tokens_per_second"],
        "time_to_first_token": row["time_to_first_token"],
        "token_count": row["token_count"],
        "reference_used": bool(row["reference_used"]),
        "lora_name": row["lora_name"],
        "lora_scale": row["lora_scale"],
        "created_at": row["created_at"],
        "image_url": f"/media/images/{row['id']}",
        "thumbnail_url": f"/media/thumbnails/{row['id']}",
        "filename": Path(row["image_path"]).name,
    }


def history(limit: int = 200) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
    return [row_to_public(row) for row in rows]


def generation_by_id(generation_id: str) -> sqlite3.Row | None:
    with database() as connection:
        return connection.execute("SELECT * FROM generations WHERE id = ?", (generation_id,)).fetchone()


def validate_integer(value: Any, name: str, minimum: int, maximum: int, multiple: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.") from None
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    if multiple and parsed % multiple:
        raise ValueError(f"{name} must be a multiple of {multiple}.")
    return parsed


def validate_generation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("Enter a prompt before generating.")
    if len(prompt) > 10_000:
        raise ValueError("The prompt is too long (10,000 character maximum).")

    model_id = str(payload.get("model_id", "flux2_klein_4b"))
    if model_id not in MODEL_DEFINITIONS:
        raise ValueError("Choose an available image model.")
    if not model_is_installed(model_id):
        raise ValueError("That model is not installed in the existing Hugging Face cache.")

    raw_quantization = payload.get("quantization")
    quantization = None if raw_quantization in (None, "", "none", "None") else int(raw_quantization)
    if quantization not in ALLOWED_QUANTIZATION:
        raise ValueError("Quantization must be None, 8-bit, 6-bit, or 4-bit.")

    width = validate_integer(payload.get("width", 1024), "Width", 256, 2048, 16)
    height = validate_integer(payload.get("height", 1024), "Height", 256, 2048, 16)
    steps = validate_integer(payload.get("steps", 4), "Steps", 1, 100)
    random_seed = bool(payload.get("random_seed", True))
    seed = secrets.randbelow(1_000_000_001) if random_seed else validate_integer(
        payload.get("seed", 42), "Seed", 0, 2_147_483_647
    )

    lora_path, lora_name = resolve_lora(payload.get("lora_id"))
    try:
        lora_scale = float(payload.get("lora_scale", 1.0))
    except (TypeError, ValueError):
        raise ValueError("LoRA strength must be a number.") from None
    if not 0 <= lora_scale <= 2:
        raise ValueError("LoRA strength must be between 0 and 2.")

    return {
        "prompt": prompt,
        "model_id": model_id,
        "quantization": quantization,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "lora_path": lora_path,
        "lora_name": lora_name,
        "lora_scale": lora_scale,
        "reference_generation_id": payload.get("reference_generation_id"),
        "reference_data": payload.get("reference_data"),
    }


def save_uploaded_reference(data_url: str, job_id: str) -> Path:
    match = re.fullmatch(r"data:([^;,]+);base64,(.+)", data_url, flags=re.DOTALL)
    if not match or match.group(1) not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Reference images must be PNG, JPEG, or WebP.")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("The reference image could not be read.") from None
    if len(decoded) > MAX_REFERENCE_BYTES:
        raise ValueError("Reference images must be smaller than 30 MB.")
    path = REFERENCES_DIR / f"{job_id}{ALLOWED_IMAGE_TYPES[match.group(1)]}"
    path.write_bytes(decoded)
    return path


def resolve_reference(config: dict[str, Any], job_id: str) -> tuple[Path | None, bool]:
    generation_id = config.get("reference_generation_id")
    if generation_id:
        row = generation_by_id(str(generation_id))
        if not row:
            raise ValueError("The selected reference generation no longer exists.")
        path = Path(row["image_path"])
        if not path.is_file():
            raise ValueError("The selected reference image is missing.")
        return path, False
    data_url = config.get("reference_data")
    if data_url:
        return save_uploaded_reference(str(data_url), job_id), True
    return None, False


def offline_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "HF_HOME": str(HF_HUB.parent),
            "HF_HUB_CACHE": str(HF_HUB),
            "HUGGINGFACE_HUB_CACHE": str(HF_HUB),
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return environment


def build_mflux_command(config: dict[str, Any], output_path: Path, reference_path: Path | None) -> list[str]:
    executable = EDIT_BIN if reference_path else GENERATE_BIN
    model = MODEL_DEFINITIONS[config["model_id"]]
    command = [
        str(executable),
        "--model",
        model["mflux_name"],
        "--prompt",
        config["prompt"],
        "--seed",
        str(config["seed"]),
        "--steps",
        str(config["steps"]),
        "--width",
        str(config["width"]),
        "--height",
        str(config["height"]),
        "--output",
        str(output_path),
    ]
    if config["quantization"] is not None:
        command.extend(["--quantize", str(config["quantization"])])
    if reference_path:
        command.extend(["--image-paths", str(reference_path)])
    if config["lora_path"]:
        command.extend(["--lora", str(config["lora_path"]), str(config["lora_scale"])])
    return command


def process_rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        return int(value) * 1024 if value else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def create_thumbnail(image_path: Path, thumbnail_path: Path) -> None:
    try:
        subprocess.run(
            ["/usr/bin/sips", "-Z", "360", str(image_path), "--out", str(thumbnail_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        shutil.copy2(image_path, thumbnail_path)


def fake_test_image(path: Path) -> None:
    # 1x1 opaque slate PNG used only by automated tests when LIS_TEST_MODE=1.
    encoded = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYGD4DwAB"
        "BAEAHnOcQAAAAABJRU5ErkJggg=="
    )
    path.write_bytes(base64.b64decode(encoded))


def run_generation(job_id: str, config: dict[str, Any]) -> None:
    global ACTIVE_JOB_ID, ACTIVE_PROCESS
    reference_path: Path | None = None
    delete_reference = False
    log_path = APP_SUPPORT / f"job-{job_id}.log"
    output_path = GENERATIONS_DIR / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{job_id[:8]}.png"
    thumbnail_path = THUMBNAILS_DIR / f"{job_id}.png"
    started = time.perf_counter()
    peak_memory: int | None = None
    try:
        reference_path, delete_reference = resolve_reference(config, job_id)
        command = build_mflux_command(config, output_path, reference_path)
        with JOBS_LOCK:
            JOBS[job_id].update({"state": "running", "message": "Generating locally…", "seed": config["seed"]})

        if os.environ.get("LIS_TEST_MODE") == "1":
            time.sleep(0.05)
            fake_test_image(output_path)
            peak_memory = process_rss_bytes(os.getpid())
        else:
            executable = Path(command[0])
            if not executable.is_file():
                raise RuntimeError("MFLUX is installed, but its FLUX.2 command could not be found.")
            with log_path.open("wb") as log_file:
                process = subprocess.Popen(
                    command,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=offline_environment(),
                    start_new_session=True,
                )
                ACTIVE_PROCESS = process
                while process.poll() is None:
                    if SHUTTING_DOWN.is_set():
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGTERM)
                        raise RuntimeError("Generation stopped because the app closed.")
                    rss = process_rss_bytes(process.pid)
                    if rss is not None:
                        peak_memory = max(peak_memory or 0, rss)
                    time.sleep(0.3)
                return_code = process.returncode
                ACTIVE_PROCESS = None
            if return_code != 0 or not output_path.is_file():
                details = ""
                with contextlib.suppress(OSError):
                    details = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
                if "offline" in details.lower() or "not found" in details.lower():
                    raise RuntimeError("MFLUX could not open the installed model cache. No download was attempted.")
                raise RuntimeError("MFLUX could not complete this generation. Try a smaller image or quantization.")

        elapsed = max(time.perf_counter() - started, 0.001)
        create_thumbnail(output_path, thumbnail_path)
        model = MODEL_DEFINITIONS[config["model_id"]]
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()
        with database() as connection:
            connection.execute(
                """
                INSERT INTO generations (
                    id, image_path, thumbnail_path, prompt, model_id, model_label,
                    quantization, seed, width, height, steps, generation_time,
                    seconds_per_image, steps_per_second, peak_memory_bytes,
                    gpu_utilization, tokens_per_second, time_to_first_token, token_count,
                    reference_used, lora_name, lora_scale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(output_path),
                    str(thumbnail_path),
                    config["prompt"],
                    config["model_id"],
                    model["label"],
                    config["quantization"],
                    config["seed"],
                    config["width"],
                    config["height"],
                    config["steps"],
                    elapsed,
                    elapsed,
                    config["steps"] / elapsed,
                    peak_memory,
                    None,
                    None,
                    None,
                    None,
                    int(reference_path is not None),
                    config["lora_name"],
                    config["lora_scale"] if config["lora_path"] else None,
                    created_at,
                ),
            )
        row = generation_by_id(job_id)
        with JOBS_LOCK:
            JOBS[job_id].update(
                {
                    "state": "complete",
                    "message": "Generation complete",
                    "generation": row_to_public(row) if row else None,
                }
            )
    except Exception as error:
        with contextlib.suppress(OSError):
            output_path.unlink()
        with contextlib.suppress(OSError):
            thumbnail_path.unlink()
        with JOBS_LOCK:
            JOBS[job_id].update({"state": "error", "message": str(error)})
        if os.environ.get("LIS_DEBUG") == "1":
            traceback.print_exc()
    finally:
        if delete_reference and reference_path:
            with contextlib.suppress(OSError):
                reference_path.unlink()
        with contextlib.suppress(OSError):
            log_path.unlink()
        with JOBS_LOCK:
            ACTIVE_JOB_ID = None
        ACTIVE_PROCESS = None


def start_generation(payload: dict[str, Any]) -> dict[str, Any]:
    global ACTIVE_JOB_ID
    config = validate_generation_payload(payload)
    with JOBS_LOCK:
        if ACTIVE_JOB_ID and JOBS.get(ACTIVE_JOB_ID, {}).get("state") in {"queued", "running"}:
            raise RuntimeError("A generation is already running.")
        job_id = str(uuid.uuid4())
        JOBS[job_id] = {
            "id": job_id,
            "state": "queued",
            "message": "Preparing model…",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        ACTIVE_JOB_ID = job_id
    threading.Thread(target=run_generation, args=(job_id, config), daemon=True).start()
    return JOBS[job_id].copy()


def delete_generation(generation_id: str) -> bool:
    row = generation_by_id(generation_id)
    if not row:
        return False
    with database() as connection:
        connection.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
    for key in ("image_path", "thumbnail_path"):
        if row[key]:
            with contextlib.suppress(OSError):
                Path(row[key]).unlink()
    return True


def terminate_generation() -> None:
    process = ACTIVE_PROCESS
    if process and process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "LocalImageStudio/1.0"

    @property
    def expected_origin(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def log_message(self, format_string: str, *args: Any) -> None:
        if os.environ.get("LIS_DEBUG") == "1":
            super().log_message(format_string, *args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-src 'none'",
        )
        super().end_headers()

    def session_valid(self) -> bool:
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("lis_session")
        return bool(morsel and secrets.compare_digest(morsel.value, self.server.session_token))

    def mutation_origin_valid(self) -> bool:
        origin = self.headers.get("Origin")
        return origin in (None, self.expected_origin)

    def require_session(self, mutation: bool = False) -> bool:
        if not self.session_valid() or (mutation and not self.mutation_origin_valid()):
            self.send_json({"error": "Unauthorized local request."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
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
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ValueError("Invalid request size.")
        try:
            decoded = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Invalid JSON request.") from None
        if not isinstance(decoded, dict):
            raise ValueError("Expected a JSON object.")
        return decoded

    def serve_file(self, path: Path, content_type: str | None = None, disposition: str | None = None) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" and "token" in query:
            supplied = query["token"][0]
            if not secrets.compare_digest(supplied, self.server.session_token):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Set-Cookie", f"lis_session={self.server.session_token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/")
            self.end_headers()
            return

        if path == "/api/health":
            self.send_json({"ok": True, "app": APP_NAME})
            return
        if not self.require_session():
            return

        if path == "/":
            self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/bootstrap":
            active = None
            with JOBS_LOCK:
                if ACTIVE_JOB_ID:
                    active = JOBS.get(ACTIVE_JOB_ID, {}).copy()
            self.send_json(
                {
                    "models": public_models(),
                    "history": history(),
                    "loras": scan_loras(),
                    "active_job": active,
                    "lora_folder_ready": True,
                }
            )
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                result = job.copy() if job else None
            if not result:
                self.send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
            else:
                self.send_json(result)
            return
        if path.startswith("/api/generations/"):
            generation_id = path.rsplit("/", 1)[-1]
            row = generation_by_id(generation_id)
            if not row:
                self.send_json({"error": "Generation not found."}, HTTPStatus.NOT_FOUND)
            else:
                self.send_json(row_to_public(row))
            return
        if path.startswith("/media/images/") or path.startswith("/media/thumbnails/"):
            generation_id = path.rsplit("/", 1)[-1]
            row = generation_by_id(generation_id)
            if not row:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            key = "thumbnail_path" if "/thumbnails/" in path else "image_path"
            media_path = Path(row[key] or row["image_path"])
            self.serve_file(media_path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.require_session(mutation=True):
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/generate":
                job = start_generation(self.read_json())
                self.send_json(job, HTTPStatus.ACCEPTED)
                return
            match = re.fullmatch(r"/api/generations/([0-9a-f-]+)/reveal", path)
            if match:
                row = generation_by_id(match.group(1))
                if not row:
                    self.send_json({"error": "Generation not found."}, HTTPStatus.NOT_FOUND)
                    return
                subprocess.Popen(["/usr/bin/open", "-R", row["image_path"]])
                self.send_json({"ok": True})
                return
            match = re.fullmatch(r"/api/models/([a-z0-9_]+)/reveal", path)
            if match:
                model_id = match.group(1)
                if model_id not in MODEL_DEFINITIONS or not model_cache_path(model_id).exists():
                    self.send_json({"error": "Installed model not found."}, HTTPStatus.NOT_FOUND)
                    return
                subprocess.Popen(["/usr/bin/open", str(model_cache_path(model_id))])
                self.send_json({"ok": True})
                return
            if path == "/api/loras/reveal":
                subprocess.Popen(["/usr/bin/open", str(LORAS_DIR)])
                self.send_json({"ok": True})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, HTTPStatus.CONFLICT)

    def do_DELETE(self) -> None:
        if not self.require_session(mutation=True):
            return
        path = urllib.parse.urlparse(self.path).path
        match = re.fullmatch(r"/api/generations/([0-9a-f-]+)", path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if delete_generation(match.group(1)):
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "Generation not found."}, HTTPStatus.NOT_FOUND)


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], session_token: str):
        self.session_token = session_token
        super().__init__(address, handler)


def signal_shutdown(_signum: int, _frame: Any) -> None:
    SHUTTING_DOWN.set()
    terminate_generation()
    if SERVER:
        threading.Thread(target=SERVER.shutdown, daemon=True).start()


def main() -> int:
    global SERVER
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=None)
    arguments = parser.parse_args()
    token = arguments.token or secrets.token_urlsafe(32)

    ensure_directories()
    initialize_database()
    signal.signal(signal.SIGTERM, signal_shutdown)
    signal.signal(signal.SIGINT, signal_shutdown)
    SERVER = StudioServer(("127.0.0.1", arguments.port), StudioHandler, token)
    port = SERVER.server_address[1]
    print(f"READY {port} {token}", flush=True)
    try:
        SERVER.serve_forever(poll_interval=0.2)
    finally:
        SHUTTING_DOWN.set()
        terminate_generation()
        SERVER.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
