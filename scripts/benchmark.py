"""Measure real HTTP submission + independent worker processes; never reset user data.
Run on an otherwise idle, migrated test database with the API already started.
"""

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import Attempt, Job, Session


def benchmark(count, workers, base_url, timeout):
    ids, latencies, processes = [], [], []
    started = time.perf_counter()
    try:
        for _ in range(workers):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "app.runtime", "worker"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "app.runtime", "scheduler"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        with httpx.Client(
            trust_env=False, base_url=base_url, headers={"X-API-Key": settings.api_key}, timeout=30
        ) as client:
            for _ in range(count):
                before = time.perf_counter()
                response = client.post(
                    "/api/v1/jobs", json={"task_type": "fibonacci", "payload": {"n": 25}}
                )
                response.raise_for_status()
                latencies.append(time.perf_counter() - before)
                ids.append(response.json()["job_id"])
            deadline = started + timeout
            while time.perf_counter() < deadline:
                with Session() as s:
                    jobs = s.scalars(select(Job).where(Job.id.in_(ids))).all()
                if all(j.status in {"completed", "failed", "cancelled"} for j in jobs):
                    break
                time.sleep(0.2)
            else:
                raise TimeoutError("Benchmark workload did not finish")
        elapsed = time.perf_counter() - started
        with Session() as s:
            durations = s.scalars(
                select(Attempt.duration).where(
                    Attempt.job_id.in_(ids), Attempt.status == "completed"
                )
            ).all()
        return {
            "jobs": count,
            "workers": workers,
            "elapsed_seconds": round(elapsed, 3),
            "submission_mean_ms": round(statistics.mean(latencies) * 1000, 3),
            "submission_p95_ms": round(
                sorted(latencies)[int(0.95 * (len(latencies) - 1))] * 1000, 3
            ),
            "throughput_jobs_per_second": round(count / elapsed, 3),
            "mean_attempt_seconds": round(statistics.mean(durations), 4) if durations else None,
            "mean_queue_wait_seconds": round(
                statistics.mean(
                    (j.started_at - j.created_at).total_seconds() for j in jobs if j.started_at
                ),
                4,
            ),
            "completed": sum(j.status == "completed" for j in jobs),
            "failed": sum(j.status == "failed" for j in jobs),
        }
    finally:
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 4])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--environment", required=True, help="Describe database, hardware, and service placement"
    )
    parser.add_argument("--output", default="docs/benchmark-results.json")
    args = parser.parse_args()
    report = {
        "environment": args.environment,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "workload": "fibonacci(25), sequential HTTP submissions, fresh child process per task",
        "results": [],
    }
    for count in args.counts:
        for workers in args.workers:
            row = benchmark(count, workers, args.base_url, args.timeout)
            report["results"].append(row)
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
