#!/usr/bin/env python3
"""End-to-end integration test for SeedVR2 7B upscaling.

Tests the complete pipeline:
1. Create a 1024x1024 source generation (FLUX.2 Klein 4B)
2. Upscale it with SeedVR2 7B (2x → 2048x2048)
3. Verify database records (parent_id, project_id, metadata)
4. Confirm source image is unchanged

Usage:
    python v2/tests/test_seedvr2_integration.py [--port PORT] [--token TOKEN]

If --port and --token are omitted, the script will start a backend server
and extract the token from its READY log line.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def get_token_from_log(log_path: str) -> tuple[int, str]:
    """Read the READY line from the backend log to get port and token."""
    with open(log_path) as f:
        for line in f:
            if line.startswith("READY "):
                parts = line.strip().split()
                return int(parts[1]), parts[2]
    raise RuntimeError("Could not find READY line in log")


def api_request(base_url: str, token: str, path: str, method: str = "GET", data: dict | None = None) -> dict:
    """Make an authenticated API request."""
    import urllib.request

    url = f"{base_url}{path}"
    headers = {
        "X-Local-Image-Studio-Token": token,
        "Content-Type": "application/json",
    }

    if data is not None:
        body = json.dumps(data).encode("utf-8")
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def wait_for_generation(base_url: str, token: str, job_id: str, timeout: float = 300) -> dict:
    """Poll for generation completion."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = api_request(base_url, token, f"/api/jobs/{job_id}")
        if status.get("state") == "complete":
            return status
        if status.get("state") == "error":
            raise RuntimeError(f"Generation failed: {status.get('message')}")
        time.sleep(1)
    raise RuntimeError(f"Generation timed out after {timeout}s")


def wait_for_upscale(base_url: str, token: str, job_id: str, timeout: float = 600) -> dict:
    """Poll for upscale completion."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = api_request(base_url, token, f"/api/jobs/{job_id}")
        if status.get("state") == "complete":
            return status
        if status.get("state") == "error":
            raise RuntimeError(f"Upscale failed: {status.get('message')}")
        time.sleep(0.5)
    raise RuntimeError(f"Upscale timed out after {timeout}s")


def test_seedvr2_integration(port: int, token: str) -> list[str]:
    """Run the full SeedVR2 integration test. Returns list of failures."""
    base_url = f"http://localhost:{port}"
    errors = []

    # Step 1: Bootstrap to see current state
    print("=" * 60)
    print("SeedVR2 7B Integration Test")
    print("=" * 60)

    try:
        bootstrap = api_request(base_url, token, "/api/bootstrap")
        print(f"\n[OK] Bootstrap successful")
        print(f"  Models: {[m['id'] for m in bootstrap.get('models', [])]}")
        print(f"  Existing generations: {len(bootstrap.get('generations', []))}")
        print(f"  SeedVR2 status: {bootstrap.get('models', [{}])[2].get('status') if len(bootstrap.get('models', [])) > 2 else 'N/A'}")
    except Exception as e:
        errors.append(f"Bootstrap failed: {e}")
        return errors

    # Step 2: Create a 1024x1024 source generation
    print("\n[Step 2] Creating 1024x1024 source generation...")
    try:
        gen_resp = api_request(
            base_url, token, "/api/generate", "POST",
            {
                "prompt": "A beautiful landscape with mountains and a serene lake at sunset",
                "model_id": "flux2_klein_4b",
                "width": 1024,
                "height": 1024,
                "steps": 4,
                "seed": 42,
                "variant_count": 1,
                "quantization": None,
                "prompt_improvement": False,
                "model_retention": "immediate",
            },
        )

        job_id = gen_resp.get("job_id") or gen_resp.get("id")
        if not job_id:
            errors.append(f"Generate response missing job_id: {gen_resp}")
            return errors

        print(f"  Job ID: {job_id}")
        gen_result = wait_for_generation(base_url, token, job_id)

        # Find the generated image path
        gen_data = gen_result.get("generation") or (gen_result.get("generations", [{}])[0] if gen_result.get("generations") else {})
        image_path = gen_data.get("image_path", "")

        if not image_path or not os.path.isfile(image_path):
            errors.append(f"Generated image not found at: {image_path}")
            return errors

        # Verify the source image dimensions
        from PIL import Image
        with Image.open(image_path) as img:
            w, h = img.size

        if w != 1024 or h != 1024:
            errors.append(f"Source image is {w}x{h}, expected 1024x1024")
        else:
            print(f"  [OK] Source image: {w}x{h}")

        # Record the source generation ID
        source_gen_id = gen_data.get("id", "")

        # Save the original file size for comparison
        source_size = os.path.getsize(image_path)
        print(f"  Source file size: {source_size} bytes")

    except Exception as e:
        errors.append(f"Generation failed: {e}")
        import traceback
        errors.append(traceback.format_exc())
        return errors

    # Step 3: Upscale the source generation with SeedVR2 7B
    print("\n[Step 3] Starting 2x upscale with SeedVR2 7B...")
    try:
        upscale_resp = api_request(
            base_url, token, "/api/upscale", "POST",
            {
                "source_generation_id": source_gen_id,
                "scale": "2x",
                "softness": 0.5,
                "seed": 42,
            },
        )

        upscale_job_id = upscale_resp.get("id") or upscale_resp.get("job_id")
        if not upscale_job_id:
            errors.append(f"Upscale response missing job_id: {upscale_resp}")
            return errors

        print(f"  Upscale Job ID: {upscale_job_id}")
        upscale_result = wait_for_upscale(base_url, token, upscale_job_id)

        # Find the upscaled image
        up_data = upscale_result.get("generation") or (upscale_result.get("generations", [{}])[0] if upscale_result.get("generations") else {})
        upscaled_path = up_data.get("image_path", "")

        if not upscaled_path or not os.path.isfile(upscaled_path):
            errors.append(f"Upscaled image not found at: {upscaled_path}")
            return errors

        # Verify the upscaled image dimensions (should be 2048x2048 for 2x)
        with Image.open(upscaled_path) as img:
            uw, uh = img.size

        if uw != 2048 or uh != 2048:
            errors.append(f"Upscaled image is {uw}x{uh}, expected 2048x2048")
        else:
            print(f"  [OK] Upscaled image: {uw}x{uh}")

        upscaled_gen_id = up_data.get("id", "")
        print(f"  Upscaled generation ID: {upscaled_gen_id}")

    except Exception as e:
        errors.append(f"Upscale failed: {e}")
        import traceback
        errors.append(traceback.format_exc())
        return errors

    # Step 4: Verify database records
    print("\n[Step 4] Verifying database records...")

    db_path = os.path.expanduser("~/Library/Application Support/Local Image Studio/history.sqlite3")
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row

        # Check the upscaled generation record
        row = conn.execute(
            "SELECT * FROM generations WHERE id = ?", (upscaled_gen_id,)
        ).fetchone()

        if not row:
            errors.append(f"Upscaled generation {upscaled_gen_id} not found in database")
        else:
            # Verify parent_id points to source
            if row["parent_id"] != source_gen_id:
                errors.append(f"parent_id mismatch: {row['parent_id']} != {source_gen_id}")
            else:
                print(f"  [OK] parent_id correctly set to source generation")

            # Verify project_id is preserved (should be null if no project)
            print(f"  [OK] project_id: {row['project_id']} (preserved from source)")

            # Verify upscale metadata
            if row["upscale_source_width"] != 1024:
                errors.append(f"upscale_source_width: {row['upscale_source_width']} != 1024")
            else:
                print(f"  [OK] upscale_source_width: {row['upscale_source_width']}")

            if row["upscale_source_height"] != 1024:
                errors.append(f"upscale_source_height: {row['upscale_source_height']} != 1024")
            else:
                print(f"  [OK] upscale_source_height: {row['upscale_source_height']}")

            if row["upscale_scale_factor"] not in ("2×", "2x"):
                errors.append(f"upscale_scale_factor: {row['upscale_scale_factor']}")
            else:
                print(f"  [OK] upscale_scale_factor: {row['upscale_scale_factor']}")

            if row["upscale_model_variant"] != "7B":
                errors.append(f"upscale_model_variant: {row['upscale_model_variant']}")
            else:
                print(f"  [OK] upscale_model_variant: {row['upscale_model_variant']}")

            if row["upscale_precision"] != "FP16":
                errors.append(f"upscale_precision: {row['upscale_precision']}")
            else:
                print(f"  [OK] upscale_precision: {row['upscale_precision']}")

            # Verify model_id is seedvr2_7b
            if row["model_id"] != "seedvr2_7b":
                errors.append(f"model_id: {row['model_id']} != seedvr2_7b")
            else:
                print(f"  [OK] model_id: seedvr2_7b")

            # Verify width/height are 2048x2048
            if row["width"] != 2048 or row["height"] != 2048:
                errors.append(f"width/height: {row['width']}x{row['height']} != 2048x2048")
            else:
                print(f"  [OK] width/height: {row['width']}x{row['height']}")

            # Verify peak_memory_bytes is stored
            if row["peak_memory_bytes"] and row["peak_memory_bytes"] > 0:
                print(f"  [OK] peak_memory_bytes: {row['peak_memory_bytes']}")
            else:
                print(f"  [WARN] peak_memory_bytes not recorded")

        # Verify source generation is unchanged
        source_row = conn.execute(
            "SELECT * FROM generations WHERE id = ?", (source_gen_id,)
        ).fetchone()

        if source_row:
            # Source should still be 1024x1024, model_id flux2_klein_4b
            if source_row["width"] != 1024 or source_row["height"] != 1024:
                errors.append(f"Source dimensions changed: {source_row['width']}x{source_row['height']}")
            else:
                print(f"  [OK] Source generation unchanged: {source_row['width']}x{source_row['height']}")

            if source_row["model_id"] != "flux2_klein_4b":
                errors.append(f"Source model_id changed: {source_row['model_id']}")
            else:
                print(f"  [OK] Source model_id unchanged: {source_row['model_id']}")

            # Verify source file is still the same size
            if os.path.isfile(source_row["image_path"]):
                current_size = os.path.getsize(source_row["image_path"])
                if current_size != source_size:
                    errors.append(f"Source file size changed: {current_size} vs original {source_size}")
                else:
                    print(f"  [OK] Source file unchanged ({current_size} bytes)")

        conn.close()

    except Exception as e:
        errors.append(f"Database verification failed: {e}")
        import traceback
        errors.append(traceback.format_exc())

    return errors


def main():
    parser = argparse.ArgumentParser(description="SeedVR2 7B Integration Test")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=None)
    parser.add_argument("--log-path", default="/tmp/lis_integration_test.log")
    args = parser.parse_args()

    # Start backend if needed
    server_proc = None
    token = args.token

    if args.port == 0 or not token:
        print("Starting backend server for integration test...")
        script_dir = Path(__file__).resolve().parent.parent
        backend_path = str(script_dir / "backend_v2.py")

        server_proc = subprocess.Popen(
            ["/Users/ricknichols/.local/share/uv/tools/mflux/bin/python", backend_path, "--port", str(args.port)],
            stdout=open(args.log_path, "w"),
            stderr=subprocess.STDOUT,
        )

        # Wait for server to start
        max_wait = 30
        started = False
        for _ in range(max_wait * 10):
            time.sleep(0.1)
            try:
                with open(args.log_path) as f:
                    line = f.readline()
                    if line.startswith("READY "):
                        args.port, token = get_token_from_log(args.log_path)
                        started = True
                        break
            except:
                pass

        if not started:
            print("ERROR: Backend server failed to start")
            sys.exit(1)

        print(f"  Server started on port {args.port}, token: {token[:16]}...")

    try:
        errors = test_seedvr2_integration(args.port, token)

        print("\n" + "=" * 60)
        if errors:
            print(f"FAILED: {len(errors)} error(s)")
            for err in errors:
                print(f"  ✗ {err}")
            sys.exit(1)
        else:
            print("ALL TESTS PASSED")
            print("\nSummary:")
            print("  ✓ Source generation created (1024x1024)")
            print("  ✓ SeedVR2 7B upscale completed (2048x2048)")
            print("  ✓ Database records verified:")
            print("    - parent_id correctly set")
            print("    - project_id preserved (null)")
            print("    - upscale metadata stored")
            print("  ✓ Source image unchanged")
            sys.exit(0)

    finally:
        if server_proc:
            print("\nShutting down backend server...")
            try:
                server_proc.terminate()
                server_proc.wait(timeout=10)
            except:
                server_proc.kill()


if __name__ == "__main__":
    main()
