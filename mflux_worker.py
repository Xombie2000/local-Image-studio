#!/usr/bin/env python3
"""Persistent MFLUX worker for Local Image Studio v2.

The worker owns at most one resident model. It receives newline-delimited JSON on
stdin and emits prefixed JSON events on stdout so normal library logging cannot
corrupt the protocol.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


PROTOCOL_PREFIX = "LISJSON "
MODEL: Any = None
MODEL_KEY: tuple[Any, ...] | None = None
MODEL_ID: str | None = None


def emit(payload: dict[str, Any]) -> None:
    print(PROTOCOL_PREFIX + json.dumps(payload, separators=(",", ":")), flush=True)


def log_telemetry(phase: str):
    import resource
    import mlx.core as mx
    try:
        active = int(mx.get_active_memory())
    except Exception:
        active = 0
    try:
        peak = int(mx.get_peak_memory())
    except Exception:
        peak = 0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"TELEMETRY|{phase}|active={active}|peak={peak}|rss={rss}")

def model_config_for(model_id: str):
    from mflux.models.common.config import ModelConfig

    if model_id == "flux2_klein_4b":
        return ModelConfig.flux2_klein_4b()
    if model_id == "flux2_klein_9b":
        return ModelConfig.flux2_klein_9b()
    raise ValueError("Unsupported model.")


def unload(request_id: str | None = None) -> None:
    global MODEL, MODEL_KEY, MODEL_ID
    previous = MODEL_ID
    if MODEL is not None:
        MODEL = None
        MODEL_KEY = None
        MODEL_ID = None
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
            mx.reset_peak_memory()
        except Exception:
            pass
    emit({"event": "status", "request_id": request_id, "status": "unloaded", "previous_model_id": previous})


class ProgressReporter:
    def __init__(self, request_id: str, variant_index: int, variant_count: int):
        self.request_id = request_id
        self.variant_index = variant_index
        self.variant_count = variant_count
        self.started = time.perf_counter()

    def call_before_loop(self, **_kwargs: Any) -> None:
        emit(
            {
                "event": "progress",
                "request_id": self.request_id,
                "phase": "generating",
                "step": 0,
                "variant_index": self.variant_index,
                "variant_count": self.variant_count,
                "elapsed": time.perf_counter() - self.started,
                "peak_memory_bytes": peak_memory(),
            }
        )

    def call_in_loop(self, t: int, config: Any, **_kwargs: Any) -> None:
        emit(
            {
                "event": "progress",
                "request_id": self.request_id,
                "phase": "generating",
                "step": int(t) + 1,
                "steps": int(config.num_inference_steps),
                "variant_index": self.variant_index,
                "variant_count": self.variant_count,
                "elapsed": time.perf_counter() - self.started,
                "peak_memory_bytes": peak_memory(),
            }
        )


def peak_memory() -> int | None:
    try:
        import mlx.core as mx

        return int(mx.get_peak_memory())
    except Exception:
        return None


def active_memory() -> int | None:
    try:
        import mlx.core as mx

        return int(mx.get_active_memory())
    except Exception:
        return None


def ensure_model(params: dict[str, Any], request_id: str):
    global MODEL, MODEL_KEY, MODEL_ID
    model_id = params["model_id"]
    quantization = params.get("quantization")
    reference = bool(params.get("reference_paths"))
    lora_paths = params.get("lora_paths") or None
    lora_scales = params.get("lora_scales") or None
    key = (model_id, quantization, reference, tuple(lora_paths or []), tuple(lora_scales or []))
    if MODEL is not None and MODEL_KEY == key:
        emit(
            {
                "event": "status",
                "request_id": request_id,
                "status": "loaded",
                "model_id": model_id,
                "reused": True,
                "active_memory_bytes": active_memory(),
            }
        )
        return MODEL

    if MODEL is not None:
        unload(request_id)
    emit({"event": "status", "request_id": request_id, "status": "loading", "model_id": model_id})
    started = time.perf_counter()
    if reference:
        from mflux.models.flux2.variants import Flux2KleinEdit

        model_class = Flux2KleinEdit
    else:
        from mflux.models.flux2.variants import Flux2Klein

        model_class = Flux2Klein
    MODEL = model_class(
        model_config=model_config_for(model_id),
        quantize=quantization,
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )
    MODEL_KEY = key
    MODEL_ID = model_id
    emit(
        {
            "event": "status",
            "request_id": request_id,
            "status": "loaded",
            "model_id": model_id,
            "reused": False,
            "load_seconds": time.perf_counter() - started,
            "active_memory_bytes": active_memory(),
        }
    )
    return MODEL


def generate(command: dict[str, Any]) -> None:
    request_id = command["request_id"]
    params = command["params"]
    try:
        import mlx.core as mx

        mx.reset_peak_memory()
        model = ensure_model(params, request_id)
        outputs = params["outputs"]
        seeds = params["seeds"]
        results = []
        for index, (output, seed) in enumerate(zip(outputs, seeds, strict=True), start=1):
            model.callbacks.in_loop.clear()
            model.callbacks.before_loop.clear()
            model.callbacks.after_loop.clear()
            model.callbacks.interrupt.clear()
            reporter = ProgressReporter(request_id, index, len(outputs))
            model.callbacks.register(reporter)
            started = time.perf_counter()
            common = {
                "seed": int(seed),
                "prompt": params["prompt"],
                "num_inference_steps": int(params["steps"]),
                "width": int(params["width"]),
                "height": int(params["height"]),
                "guidance": 1.0,
            }
            if params.get("reference_paths"):
                image = model.generate_image(**common, image_paths=[Path(path) for path in params["reference_paths"]])
            else:
                image = model.generate_image(**common)
            image.save(path=output)
            elapsed = max(time.perf_counter() - started, 0.001)
            results.append(
                {
                    "output": output,
                    "seed": seed,
                    "generation_time": elapsed,
                    "peak_memory_bytes": peak_memory(),
                    "active_memory_bytes": active_memory(),
                }
            )
            gc.collect()
            mx.clear_cache()
        emit({"event": "result", "request_id": request_id, "results": results, "model_id": MODEL_ID})
    except Exception as error:
        emit(
            {
                "event": "error",
                "request_id": request_id,
                "message": str(error) or error.__class__.__name__,
                "traceback": traceback.format_exc()[-5000:] if os.environ.get("LIS_DEBUG") == "1" else None,
            }
        )


def upscale(command: dict[str, Any]) -> None:
    request_id = command["request_id"]
    params = command["params"]
    try:
        from mflux.models.seedvr2 import SeedVR2
        from mflux.models.common.config import ModelConfig
        from pathlib import Path as MPath
        import mlx.core as mx

        mx.reset_peak_memory()
        request_id = command["request_id"]
        params = command["params"]
        log_telemetry("A")
        output_path = params["output_path"]
        image_path = params["image_path"]
        resolution_str = str(params.get("resolution", "2x"))
        softness = float(params.get("softness", 0.5))
        quantization = params.get("quantization")

        # Convert resolution string (e.g. "2x", "4x") to ScaleFactor object.
        # SeedVR2Util.preprocess_image() expects either an int or a ScaleFactor;
        # passing the raw string causes "unsupported operand type(s) for /: 'str' and 'int'."
        from mflux.utils.scale_factor import ScaleFactor

        resolution = ScaleFactor.parse(resolution_str)

        emit({"event": "status", "request_id": request_id, "status": "loading", "model_id": "seedvr2_7b"})
        started = time.perf_counter()

        model_config = ModelConfig.seedvr2_7b()
        model = SeedVR2(
            model_config=model_config,
            quantize=quantization,
        )
        log_telemetry("B")

        emit(
            {
                "event": "status",
                "request_id": request_id,
                "status": "loaded",
                "model_id": "seedvr2_7b",
                "reused": False,
                "load_seconds": time.perf_counter() - started,
                "active_memory_bytes": active_memory(),
            }
        )

        started = time.perf_counter()
        log_telemetry("C")
        result_image = model.generate_image(
            seed=int(params.get("seed", 42)),
            image_path=MPath(image_path),
            resolution=resolution,
            softness=softness,
        )
        log_telemetry("D")
        result_image.save(path=output_path)
        log_telemetry("E")

        elapsed = max(time.perf_counter() - started, 0.001)

        # Explicit cleanup to reclaim memory
        del result_image
        del model
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass

        emit(
            {
                "event": "result",
                "request_id": request_id,
                "output_path": output_path,
                "generation_time": elapsed,
                "peak_memory_bytes": peak_memory(),
                "active_memory_bytes": active_memory(),
            }
        )
    except Exception as error:
        emit(
            {
                "event": "error",
                "request_id": request_id,
                "message": str(error) or error.__class__.__name__,
                "traceback": traceback.format_exc()[-5000:] if os.environ.get("LIS_DEBUG") == "1" else None,
            }
        )


def main() -> int:
    emit({"event": "ready", "status": "unloaded"})
    for line in sys.stdin:
        try:
            command = json.loads(line)
            action = command.get("action")
            if action == "generate":
                generate(command)
            elif action == "unload":
                unload(command.get("request_id"))
                emit({"event": "result", "request_id": command.get("request_id"), "ok": True})
            elif action == "shutdown":
                unload(command.get("request_id"))
                emit({"event": "result", "request_id": command.get("request_id"), "ok": True})
                return 0
            elif action == "status":
                emit(
                    {
                        "event": "result",
                        "request_id": command.get("request_id"),
                        "status": "loaded" if MODEL is not None else "unloaded",
                        "model_id": MODEL_ID,
                        "active_memory_bytes": active_memory(),
                    }
                )
            elif action == "upscale":
                upscale(command)
            else:
                emit(
                    {
                        "event": "error",
                        "request_id": command.get("request_id"),
                        "message": f"Unknown action: {action}",
                    }
                )
        except Exception as error:
            emit({"event": "error", "request_id": None, "message": str(error)})
    unload(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())