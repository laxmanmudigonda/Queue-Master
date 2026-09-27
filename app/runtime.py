"""Independent worker/scheduler entry points; one bounded child process per task."""

import json
import logging
import multiprocessing as mp
import signal
import socket
import sys
import time
from datetime import timedelta

from sqlalchemy import update

from app.config import settings
from app.db import Job, Session, Worker, now, uid
from app.queue import pop
from app.service import claim, finish, reconcile
from app.tasks import execute

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)
STOP = False


def stop(*_):
    global STOP
    STOP = True


def child(conn, job):
    try:
        try:
            result = execute(job.task_type, job.payload, job.id, job.attempt_count)
            outcome = (result, None)
        except Exception as exc:
            outcome = (None, f"{type(exc).__name__}: {exc}"[:2000])
        try:
            conn.send(outcome)
        except (BrokenPipeError, EOFError, OSError):
            # The parent may have crashed; durable lease recovery owns the outcome.
            pass
    finally:
        conn.close()


def heartbeat(worker_id: str, job: Job | None = None) -> bool:
    with Session.begin() as s:
        s.execute(
            update(Worker)
            .where(Worker.id == worker_id)
            .values(last_heartbeat=now(), status="busy" if job else "idle")
        )
        if job:
            result = s.execute(
                update(Job)
                .where(
                    Job.id == job.id,
                    Job.status == "running",
                    Job.lease_token == job.lease_token,
                    Job.lease_until > now(),
                )
                .values(lease_until=now() + timedelta(seconds=settings.lease_seconds))
            )
            return result.rowcount == 1
    return True


def run_job(job: Job, worker_id: str) -> None:
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=child, args=(sender, job), daemon=True)
    process.start()
    sender.close()
    next_heartbeat = 0.0
    try:
        while not STOP:
            if time.monotonic() >= next_heartbeat:
                if not heartbeat(worker_id, job):
                    return
                next_heartbeat = time.monotonic() + settings.lease_seconds / 3
            if receiver.poll(0.1):
                try:
                    result, error = receiver.recv()
                except EOFError:
                    result, error = None, "Task process exited without a result"
                finish(job.id, job.lease_token, result, error)
                return
            if not process.is_alive():
                finish(job.id, job.lease_token, error="Task process exited without a result")
                return
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join()
        receiver.close()


def worker() -> None:
    worker_id = uid()
    registered = False
    while not STOP:
        try:
            if not registered:
                with Session.begin() as s:
                    s.merge(Worker(id=worker_id, hostname=socket.gethostname()))
                registered = True
            heartbeat(worker_id)
            job_id = pop()
            job = claim(job_id, worker_id) if job_id else None
            if job:
                log.info(
                    json.dumps(
                        {
                            "event": "claimed",
                            "job_id": job.id,
                            "worker_id": worker_id,
                            "attempt": job.attempt_count,
                        }
                    )
                )
                run_job(job, worker_id)
            else:
                time.sleep(settings.poll_seconds)
        except Exception as exc:
            log.warning(
                json.dumps({"event": "worker_unavailable", "error_type": type(exc).__name__})
            )
            time.sleep(settings.poll_seconds)
    try:
        with Session.begin() as s:
            s.execute(update(Worker).where(Worker.id == worker_id).values(status="stopped"))
    except Exception:
        pass


def scheduler() -> None:
    while not STOP:
        try:
            reconcile()
        except Exception as exc:
            log.warning(
                json.dumps({"event": "scheduler_unavailable", "error_type": type(exc).__name__})
            )
        time.sleep(settings.scheduler_seconds)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    {"worker": worker, "scheduler": scheduler}[sys.argv[1]]()
