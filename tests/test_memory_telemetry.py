import subprocess
import json
import time
import os
import psutil
from pathlib import Path
from PIL import Image

def run_test():
    workspace_dir = Path("/Users/ricknichols/LocalImageStudio/v2")
    worker_script = workspace_dir / "mflux_worker.py"
    test_input = workspace_dir / "test_input.png"
    test_output = workspace_dir / "test_output.png"
    
    # Create a 1024x1024 dummy image
    print(f"Creating dummy image: {test_input}")
    img = Image.new('RGB', (1024, 1024), color=(73, 108, 151))
    img.save(test_input)

    # Start the worker
    print(f"Starting worker: {worker_script}")
    process = subprocess.Popen(
        ["python3", str(worker_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Function to poll worker for completion or errors
    def monitor_worker(proc, timeout=300):
        start_time = time.time()
        while time.time() - start_time < timeout:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("TELEMETRY|"):
                yield ("telemetry", line.strip())
            elif "LISJSON" in line:
                try:
                    msg = json.loads(line[len("LISJSON "):])
                    yield ("event", msg)
                except Exception:
                    pass
            elif "error" in line.lower():
                yield ("error", line.strip())
        
    # We'll use a thread to read stdout so we don't block
    import threading
    import queue
    event_queue = queue.Queue()

    def worker_reader(proc):
        for type, val in monitor_worker(proc):
            event_queue.put((type, val))

    t = threading.Thread(target=worker_reader, args=(process,), daemon=True)
    t.start()

    # Wait for worker to be ready
    print("Waiting for worker readiness...")
    ready = False
    while not ready:
        try:
            type, val = event_queue.get(timeout=10)
            if type == "event" and val.get("event") == "ready":
                ready = True
        except queue.Empty:
            print("Timeout waiting for ready...")
            break
    
    if not ready:
        process.kill()
        return

    # Prepare the upscale command
    cmd = {
        "action": "upscale",
        "request_id": "test_task_1",
        "params": {
            "image_path": str(test_input),
            "output_path": str(test_output),
            "resolution": "2x",
            "softness": 0.5,
            "seed": 42,
            "quantization": None
        }
    }
    
    print(f"Sending upscale command: {cmd}")
    process.stdin.write(json.dumps(cmd) + "\n")
    process.stdin.flush()

    # Monitoring RSS
    rss_history = []
    def monitor_rss(proc):
        try:
            p = psutil.Process(proc.pid)
            while proc.poll() is None:
                rss_history.append(p.memory_info().rss / (1024 * 1024))
                time.sleep(0.2)
        except Exception:
            pass
    
    m_thread = threading.Thread(target=monitor_rss, args=(process,), daemon=True)
    m_thread.start()

    # Results collection
    telemetry_data = []
    job_complete = False
    start_time = time.time()
    
    while time.time() - start_time < 600:
        try:
            type, val = event_queue.get(timeout=0.1)
            if type == "telemetry":
                telemetry_data.append(val)
            elif type == "event" and val.get("event") == "result":
                job_complete = True
                # Capture stats immediately after result event
                p = psutil.Process(process.pid)
                rss_history.append(p.memory_info().rss / (1024 * 1024))
                break
            elif type == "error":
                print(f"Error: {val}")
                job_complete = True
                break
        except queue.Empty:
            continue

    # If job finished, wait 5s and 15s
    if job_complete:
        print("Job completed. Waiting for stabilization...")
        time.sleep(5)
        p = psutil.Process(process.pid)
        rss_history.append(p.memory_info().rss / (1024 * 1024))
        time.sleep(10)
        rss_history.append(p.memory_info().rss / (1024 * 1024))

    process.terminate()
    process.wait()

    print("\n--- TEST RESULTS ---")
    print(f"Telemetry logs: {telemetry_data}")
    print(f"RSS History (MB): {rss_history}")
    
    # Parsing telemetry for the requested table
    # TELEMETRY|{phase}|active={active}|peak={peak}|rss={rss}
    
    # We'll simplify this for the report.
    # I will print a summary of what I found.
    summary = {}
    for entry in telemetry_data:
        parts = entry.split('|')
        if len(parts) < 5: continue
        phase = parts[1]
        active = int(parts[2].split('=')[1])
        peak = int(parts[3].split('=')[1])
        rss = float(parts[4].split('=')[1])
        summary[phase] = {"active": active, "peak": peak, "rss": rss}
    
    print("\nSummary Table Content:")
    print(f"Parsed Summary: {summary}")
    print(f"RSS entries captured: {len(rss_history)}")

if __name__ == "__main__":
    run_test()
