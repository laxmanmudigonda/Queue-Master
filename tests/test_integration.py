import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import Attempt, Counter, Job, Session, Worker, engine, now, uid
from app.main import Submission, app
from app.queue import pop, publish, redis
from app.service import claim, finish, reconcile, submit
from app.tasks import execute

pytestmark = pytest.mark.usefixtures("infrastructure")
client = TestClient(app, headers={"X-API-Key": settings.api_key})


def make(task="fibonacci", payload=None, **kw):
    return submit(Submission(task_type=task, payload=payload or {"n": 10}, **kw), None)[0]


def worker_id():
    key = uid()
    with Session.begin() as s:
        s.add(Worker(id=key, hostname="test"))
    return key


def test_api_and_idempotency():
    body = {"task_type": "fibonacci", "payload": {"n": 25}}
    response = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "one"})
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert (
        client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "one"}).status_code
        == 200
    )
    body["payload"]["n"] = 26
    assert (
        client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "one"}).status_code
        == 409
    )
    assert client.get(f"/api/v1/jobs/{job_id}/result").status_code == 409
    job = claim(pop(), worker_id())
    assert finish(job.id, job.lease_token, execute(job.task_type, job.payload, job.id, 1))
    assert client.get(f"/api/v1/jobs/{job_id}/result").json()["result"]["value"] == "75025"
    assert len(client.get(f"/api/v1/jobs/{job_id}/attempts").json()) == 1
    assert client.get("/api/v1/stats").json()["completed"] == 1
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 409


def test_auth_validation_and_body_limit():
    assert TestClient(app).get("/api/v1/stats").status_code == 401
    assert (
        client.post(
            "/api/v1/jobs", json={"task_type": "fibonacci", "payload": {"n": -1}}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/jobs", content=b"x" * (settings.request_limit + 1)).status_code == 413
    )
    assert client.get("/api/v1/jobs/missing").status_code == 404


def test_priority_delay_cancel():
    low = make(priority="low")
    high = make(priority="high")
    delayed = make(scheduled_at=now() + timedelta(hours=1))
    assert pop() == high.id
    assert pop() == low.id
    assert pop() is None
    assert claim(delayed.id, worker_id()) is None
    assert client.post(f"/api/v1/jobs/{delayed.id}/cancel").status_code == 200
    assert client.post(f"/api/v1/jobs/{delayed.id}/retry").status_code == 409


def test_retry_dead_letter_manual():
    job = make(max_retries=1)
    wid = worker_id()
    first = claim(job.id, wid)
    finish(job.id, first.lease_token, error="failure")
    with Session.begin() as s:
        row = s.get(Job, job.id)
        assert row.status == "retrying"
        row.scheduled_at = now() - timedelta(seconds=1)
    reconcile()
    second = claim(job.id, wid)
    finish(job.id, second.lease_token, error="again")
    assert client.get("/api/v1/dead-letter").json()["total"] == 1
    assert client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 200
    third = claim(job.id, wid)
    assert third.attempt_count == 3
    assert finish(job.id, third.lease_token, {"ok": True})


def test_expired_lease_and_fencing():
    job = make()
    old = claim(job.id, worker_id())
    with Session.begin() as s:
        s.get(Job, job.id).lease_until = now() - timedelta(seconds=1)
    assert not finish(job.id, old.lease_token, {"stale": True})
    reconcile()
    with Session.begin() as s:
        row = s.get(Job, job.id)
        assert row.status == "pending"
        row.scheduled_at = now() - timedelta(seconds=1)
    new = claim(job.id, worker_id())
    assert not finish(job.id, old.lease_token, {"stale": True})
    assert finish(job.id, new.lease_token, {"fresh": True})
    with Session() as s:
        assert s.get(Job, job.id).result == {"fresh": True}
        assert (
            s.scalar(select(Attempt).where(Attempt.lease_token == old.lease_token)).status
            == "abandoned"
        )


def test_redis_loss_rebuilt_and_duplicate_delivery():
    job = make()
    redis.delete(settings.queue_key)
    reconcile()
    assert pop() == job.id
    first = claim(job.id, worker_id())
    publish([job])
    assert claim(pop(), worker_id()) is None
    finish(job.id, first.lease_token, {})
    reconcile()
    assert pop() is None


def test_counter_receipt():
    job = make("idempotent_counter", {"name": "demo"})
    a = execute(job.task_type, job.payload, job.id, 1)
    b = execute(job.task_type, job.payload, job.id, 2)
    assert a == b
    with Session() as s:
        assert s.get(Counter, "demo").value == 1


def test_database_pool_reconnect():
    job = make()
    engine.dispose()
    with Session() as s:
        assert s.get(Job, job.id).id == job.id


def test_concurrent_claims_and_submissions():
    if os.getenv("PGLITE_VALIDATION"):
        pytest.skip("Requires native PostgreSQL multi-backend locking")
    job = make()
    workers = [worker_id() for _ in range(8)]
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(lambda w: claim(job.id, w), workers))
    assert sum(c is not None for c in claims) == 1
    data = Submission(task_type="fibonacci", payload={"n": 5})
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: submit(data, "concurrent"), range(16)))
    assert len({r[0].id for r in results}) == 1
    assert sum(r[1] for r in results) == 1


def test_database_terminated_connection_recovers():
    if os.getenv("PGLITE_VALIDATION"):
        pytest.skip("Requires native PostgreSQL backend processes")
    connection = engine.connect()
    pid = connection.scalar(text("SELECT pg_backend_pid()"))
    connection.close()
    import psycopg

    with psycopg.connect(
        settings.database_url.replace("postgresql+psycopg", "postgresql"), autocommit=True
    ) as killer:
        killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
    assert make().id


def wait_status(job_id, status, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session() as s:
            row = s.get(Job, job_id)
            if row.status == status:
                return row
        time.sleep(0.1)
    raise AssertionError(f"Job did not reach {status}")


def test_real_worker_process():
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.runtime", "worker"], stdout=subprocess.DEVNULL
    )
    try:
        job = make()
        row = wait_status(job.id, "completed")
        assert row.result["value"] == "55"
    finally:
        worker.terminate()
        worker.wait(timeout=10)


def test_process_crash_recovery():
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.runtime", "worker"], stdout=subprocess.DEVNULL
    )
    other = None
    try:
        job = make("long_running", {"seconds": 2})
        wait_status(job.id, "running")
        killed_at = time.monotonic()
        worker.kill()
        worker.wait(timeout=5)
        deadline = time.monotonic() + settings.lease_seconds + 10
        while time.monotonic() < deadline:
            reconcile()
            with Session() as s:
                if s.get(Job, job.id).status == "pending":
                    break
            time.sleep(0.1)
        other = subprocess.Popen(
            [sys.executable, "-m", "app.runtime", "worker"], stdout=subprocess.DEVNULL
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            reconcile()
            with Session() as s:
                row = s.get(Job, job.id)
                if row.status == "completed":
                    assert row.attempt_count == 2
                    print(f"Recovery elapsed: {time.monotonic() - killed_at:.3f}s")
                    return
            time.sleep(0.1)
        pytest.fail("Crash recovery did not complete")
    finally:
        for process in (worker, other):
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def test_delayed_becomes_ready():
    job = make(scheduled_at=now() + timedelta(seconds=0.2))
    assert pop() is None
    time.sleep(0.3)
    reconcile()
    assert pop() == job.id
    assert claim(job.id, worker_id()) is not None


def test_publish_failure_repairs(monkeypatch):
    from redis import ConnectionError

    import app.queue as queue

    original = queue.redis.zadd

    def fail(*args, **kwargs):
        raise ConnectionError("simulated Redis interruption")

    monkeypatch.setattr(queue.redis, "zadd", fail)
    job = make()
    assert pop() is None
    monkeypatch.setattr(queue.redis, "zadd", original)
    reconcile()
    assert pop() == job.id


def test_crash_exhaustion():
    job = make(max_retries=0)
    claimed = claim(job.id, worker_id())
    with Session.begin() as s:
        s.get(Job, job.id).lease_until = now() - timedelta(seconds=1)
    reconcile()
    with Session() as s:
        assert s.get(Job, job.id).status == "failed"
    assert not finish(job.id, claimed.lease_token, {})


def test_multiple_worker_overlap():
    processes = [
        subprocess.Popen([sys.executable, "-m", "app.runtime", "worker"], stdout=subprocess.DEVNULL)
        for _ in range(2)
    ]
    try:
        jobs = [make("long_running", {"seconds": 2}) for _ in range(2)]
        completed = [wait_status(j.id, "completed") for j in jobs]
        assert max(j.started_at for j in completed) < min(j.completed_at for j in completed)
        with Session() as s:
            attempts = s.scalars(
                select(Attempt).where(Attempt.job_id.in_([j.id for j in jobs]))
            ).all()
            assert len({a.worker_id for a in attempts}) == 2
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


def test_worker_renews_lease():
    process = subprocess.Popen(
        [sys.executable, "-m", "app.runtime", "worker"],
        env={**os.environ, "LEASE_SECONDS": "1"},
        stdout=subprocess.DEVNULL,
    )
    try:
        job = make("long_running", {"seconds": 2})
        row = wait_status(job.id, "completed")
        assert row.attempt_count == 1
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_automatic_retry_worker_and_scheduler():
    processes = [
        subprocess.Popen([sys.executable, "-m", "app.runtime", role], stdout=subprocess.DEVNULL)
        for role in ("worker", "scheduler")
    ]
    try:
        job = make("simulated_failure", {"failures": 1}, max_retries=1)
        row = wait_status(job.id, "completed")
        assert row.attempt_count == 2 and row.result == {"attempt": 2}
        with Session() as s:
            attempts = s.scalars(
                select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.attempt_number)
            ).all()
            assert [a.status for a in attempts] == ["failed", "completed"]
    finally:
        for p in processes:
            p.terminate()
        for p in processes:
            p.wait(timeout=10)
