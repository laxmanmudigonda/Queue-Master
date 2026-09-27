"""Run with API + scheduler running, all other workers stopped.
Starts and kills only its own worker process. Reports kill-to-completion time.
"""

import json
import subprocess
import sys
import time

import httpx

from app.config import settings


def main():
    processes = []
    with httpx.Client(
        trust_env=False, base_url="http://127.0.0.1:8000", headers={"X-API-Key": settings.api_key}
    ) as client:
        r = client.post(
            "/api/v1/jobs",
            json={"task_type": "long_running", "payload": {"seconds": 3}, "max_retries": 2},
        )
        r.raise_for_status()
        job_id = r.json()["job_id"]
        print(f"Created job {job_id}; waiting for this worker to claim it", flush=True)
        try:
            first = subprocess.Popen([sys.executable, "-m", "app.runtime", "worker"])
            processes.append(first)
            deadline = time.monotonic() + 240
            last_status = None
            while time.monotonic() < deadline:
                response = client.get(f"/api/v1/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if job["status"] != last_status:
                    print(
                        f"Job {job_id}: {job['status']} (attempts={job['attempt_count']})",
                        flush=True,
                    )
                    last_status = job["status"]
                if first.poll() is not None:
                    raise RuntimeError(f"Worker exited with code {first.returncode}")
                if job["status"] == "running":
                    break
                if job["status"] in {"completed", "failed", "cancelled"}:
                    raise RuntimeError(
                        f"Job reached {job['status']} before crash simulation; "
                        "stop all other workers before running this demo"
                    )
                time.sleep(0.2)
            else:
                raise RuntimeError(
                    f"Job {job_id} was not claimed within 240 seconds; "
                    f"last status={last_status}. Check worker logs and pending queue backlog."
                )
            start = time.monotonic()
            first.kill()
            first.wait()
            processes.append(subprocess.Popen([sys.executable, "-m", "app.runtime", "worker"]))
            for _ in range(int((settings.lease_seconds + 30) * 10)):
                job = client.get(f"/api/v1/jobs/{job_id}").json()
                if job["status"] == "completed":
                    report = {
                        "job_id": job_id,
                        "recovery_seconds": round(time.monotonic() - start, 3),
                        "attempts": client.get(f"/api/v1/jobs/{job_id}/attempts").json(),
                    }
                    print(json.dumps(report, indent=2))
                    assert job["attempt_count"] == 2
                    return
                time.sleep(0.1)
            raise RuntimeError("Recovery timed out")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
