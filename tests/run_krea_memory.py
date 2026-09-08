#!/usr/bin/env python3
"""Real offline Krea worker probe: before, peak, cleanup, and cleanup +5 seconds."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PREFIX = "LISJSON "
PROMPT = (
    "A futuristic heavy armored hover combat vehicle from the year 2200, with a low, wide hull and a "
    "believable integrated anti-gravity lift system. No wheels, no tracks, no landing gear. Hard-surface "
    "sci-fi realism, realistic mechanical detail, cinematic lighting, three-quarter view."
)


def read_event(process: subprocess.Popen[str], request_id: str | None = None) -> dict:
    assert process.stdout
    while line := process.stdout.readline():
        if not line.startswith(PROTOCOL_PREFIX):
            continue
        event = json.loads(line[len(PROTOCOL_PREFIX) :])
        if request_id is None or event.get("request_id") == request_id:
            return event
    raise RuntimeError("The MFLUX worker exited before returning an event.")


def request(process: subprocess.Popen[str], action: str, params: dict | None = None) -> dict:
    request_id = str(uuid.uuid4())
    assert process.stdin
    command = {"action": action, "request_id": request_id}
    if params is not None:
        command["params"] = params
    process.stdin.write(json.dumps(command, separators=(",", ":")) + "\n")
    process.stdin.flush()
    while True:
        event = read_event(process, request_id)
        if event.get("event") in {"result", "error"}:
            if event["event"] == "error":
                raise RuntimeError(event.get("message", "Krea worker failed"))
            return event


def main() -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "PYTHONUNBUFFERED": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "mflux_worker.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=environment,
    )
    try:
        ready = read_event(process)
        if ready.get("event") != "ready":
            raise RuntimeError(f"Unexpected worker startup event: {ready}")
        before = request(process, "status")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krea-memory-probe.png"
            result_event = request(
                process,
                "generate",
                {
                    "model_id": "krea2_turbo",
                    "quantization": 8,
                    "prompt": PROMPT,
                    "width": 768,
                    "height": 768,
                    "steps": 8,
                    "outputs": [str(output)],
                    "seeds": [42],
                    "reference_paths": [],
                    "lora_paths": [],
                    "lora_scales": [],
                    "unload_after": True,
                },
            )
            immediate = result_event["results"][0]
            with Image.open(output) as generated:
                dimensions = list(generated.size)
            time.sleep(5)
            after_five = request(process, "status")
        print(
            json.dumps(
                {
                    "before": {
                        "active_memory_bytes": before.get("active_memory_bytes"),
                        "cache_memory_bytes": before.get("cache_memory_bytes"),
                    },
                    "peak_memory_bytes": immediate.get("peak_memory_bytes"),
                    "immediately_after_cleanup": {
                        "active_memory_bytes": immediate.get("post_cleanup_active_memory_bytes"),
                        "cache_memory_bytes": immediate.get("post_cleanup_cache_memory_bytes"),
                    },
                    "five_seconds_after_cleanup": {
                        "active_memory_bytes": after_five.get("active_memory_bytes"),
                        "cache_memory_bytes": after_five.get("cache_memory_bytes"),
                    },
                    "generation_time": immediate.get("generation_time"),
                    "dimensions": dimensions,
                    "seed": immediate.get("seed"),
                },
                indent=2,
            )
        )
        return 0
    finally:
        if process.poll() is None:
            try:
                request(process, "shutdown")
            except Exception:
                process.terminate()
        process.wait(timeout=15)


if __name__ == "__main__":
    raise SystemExit(main())
