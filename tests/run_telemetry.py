import subprocess
import json
import time
import os
import psutil
import threading
import queue
import os
from pathlib import Path

def run_telemetry_test():
    workspace_dir = Path(__file__).resolve().parents[1]
    worker_script = workspace_dir / "mflux_worker.py"
    test_input = workspace_dir / "test_input.png"
    test_output = workspace_dir / "test_output.png"
    python_exe = os.environ.get(
        "LIS_MFLUX_PYTHON",
        str(Path.home() / ".local/share/uv/tools/mflux/bin/python"),
    )

    if not test_input.exists():
        print(f"Error: {test_input} not found.")
        return

    # Start the worker
    print(f"Starting worker: {python_exe} {worker_script}")
    process = subprocess.Popen(
        [python_exe, str(worker_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    event_queue = queue.Queue()

    def worker_reader(proc):
        for line in proc.stdout:
            if line.startswith("TELEMETRY|"):
                event_queue.put(("telemetry", line.strip()))
            elif "LISJSON" in line:
                try:
                    msg = json.loads(line[len("LISJSON "):])
                    event_queue.put(("event", msg))
                except Exception as e:
                    pass
            elif "error" in line.lower():
                event_queue.put(("error", line.strip()))

    t = threading.Thread(target=worker_reader, args=(process,), daemon=True)
    t.start()

    # Wait for ready
    print("Waiting for worker readiness...")
    ready = False
    while not ready:
        try:
            etype, evalue = event_queue.get(timeout=10)
            if etype == "event" and evalue.get("event") == "ready":
                ready = True
        except queue.Empty:
            print("Timeout waiting for worker readiness.")
            process.kill()
            return

    # Command
    cmd = {
        "action": "upscale",
        "request_id": "telemetry_test",
        "params": {
            "image_path": str(test_input),
            "output_path": str(test_output),
            "resolution": "2x",
            "softness": 0.5,
            "seed": 42,
            "quantization": None
        }
    }

    print(f"Sending command: {cmd}")
    process.stdin.write(json.dumps(cmd) + "\n")
    process.stdin.flush()

    # Monitor RSS
    rss_history = []
    def monitor_rss(proc):
        try:
            p = psutil.Process(proc.pid)
            while proc.poll() is None:
                rss_history.append(p.memory_info().rss / (1024 * 1024))
                time.sleep(0.5)
        except Exception:
            pass
    
    m_thread = threading.Thread(target=monitor_rss, args=(process,), daemon=True)
    m_thread.start()

    job_complete = False
    start_time = time.time()
    
    # Collecting telemetry and monitoring job status
    while time.time() - start_time < 600:
        try:
            etype, evalue = event_queue.get(timeout=1)
            if etype == "telemetry":
                # Log it to console as it comes
                print(f"LOG: {evalue}")
            elif etype == "event" and evalue.get("event") == "result":
                job_complete = True
                # Capture immediately after result event
                p = psutil.Process(process.pid)
                rss_history.append(p.memory_info().rss / (1024 * 1024))
                break
            elif etype == "error":
                print(f"Worker error: {evalue}")
                job_complete = True
                break
        except queue.Empty:
            continue

    if job_complete:
        print("Job completed. Waiting for stabilization...")
        time.sleep(5)
        p = psutil.Process(process.pid)
        rss_history.append(p.memory_info().rss / (1024 * 1024))
        time.sleep(10)
        rss_history.append(p.memory_info().rss / (1024 * 1024))

    process.terminate()
    process.wait()

    # Final Report
    print("\n=========================================")
    print("         TELEMETRY REPORT              ")
    print("=========================================")
    print(f"RSS History (MB): {rss_history}")
    print("=========================================")

if __name__ == "__main__":
    run_telemetry_test()
