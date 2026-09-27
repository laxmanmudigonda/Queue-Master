"""Exercise a running stack over HTTP; reads API_KEY from .env/environment."""

import json
import time

import httpx

from app.config import settings

with httpx.Client(
    trust_env=False, base_url="http://127.0.0.1:8000", headers={"X-API-Key": settings.api_key}
) as client:
    client.get("/ready").raise_for_status()
    r = client.post("/api/v1/jobs", json={"task_type": "fibonacci", "payload": {"n": 25}})
    r.raise_for_status()
    job_id = r.json()["job_id"]
    for _ in range(100):
        status = client.get(f"/api/v1/jobs/{job_id}").json()["status"]
        if status == "completed":
            result = client.get(f"/api/v1/jobs/{job_id}/result").json()
            assert result["result"]["value"] == "75025"
            print(json.dumps(result))
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("Job did not finish in 20 seconds")
