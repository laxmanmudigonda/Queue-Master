import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session as DatabaseSession

if TYPE_CHECKING:
    from app.main import Submission
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import Attempt, Event, Job, Session, now, uid
from app.queue import publish

TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "retrying", "pending", "failed"},
    "retrying": {"pending", "cancelled"},
    "failed": {"pending"},
    "completed": set(),
    "cancelled": set(),
}


class Conflict(Exception):
    pass


def transition(s: DatabaseSession, job: Job, status: str, **details: Any) -> None:
    if status not in TRANSITIONS[job.status]:
        raise Conflict(f"Cannot transition {job.status} to {status}")
    job.status = status
    job.updated_at = now()
    s.add(Event(job_id=job.id, event_type=status, details=details))


def backoff(attempt: int) -> float:
    return min(settings.max_backoff_seconds, settings.backoff_seconds * 2 ** min(attempt - 1, 30))


def submit(data: "Submission", key: str | None) -> tuple[Job, bool]:
    values = data.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    try:
        with Session.begin() as s:
            job = Job(
                id=uid(),
                task_type=data.task_type,
                payload=data.payload,
                priority={"high": 0, "normal": 1, "low": 2}[data.priority],
                max_retries=data.max_retries,
                scheduled_at=data.scheduled_at or now(),
                idempotency_key=key,
                request_hash=digest,
            )
            s.add(job)
            s.flush()
            s.add(Event(job_id=job.id, event_type="submitted", details={}))
    except IntegrityError:
        if not key:
            raise
        with Session() as s:
            job = s.scalar(select(Job).where(Job.idempotency_key == key))
            if not job:
                raise
            if job.request_hash != digest:
                raise Conflict("Idempotency key already used with another request") from None
            return job, False
    if job.scheduled_at <= now():
        publish([job])
    return job, True


def claim(job_id: str, worker_id: str) -> Job | None:
    with Session.begin() as s:
        job = s.scalar(
            select(Job)
            .where(Job.id == job_id, Job.status == "pending", Job.scheduled_at <= func.now())
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        transition(s, job, "running", worker_id=worker_id)
        job.attempt_count += 1
        job.worker_id = worker_id
        job.lease_token = uid()
        job.started_at = now()
        job.lease_until = now() + timedelta(seconds=settings.lease_seconds)
        s.add(
            Attempt(
                job_id=job.id,
                worker_id=worker_id,
                attempt_number=job.attempt_count,
                lease_token=job.lease_token,
            )
        )
        return job


def fail_locked(s: DatabaseSession, job: Job, reason: str, crash: bool = False) -> None:
    attempt = s.scalar(select(Attempt).where(Attempt.lease_token == job.lease_token))
    attempt.status = "abandoned" if crash else "failed"
    attempt.completed_at = now()
    attempt.error_message = reason
    attempt.duration = (now() - attempt.started_at).total_seconds()
    job.error_message = reason
    if job.attempt_count - job.retry_base <= job.max_retries:
        transition(s, job, "pending" if crash else "retrying", reason=reason)
        job.scheduled_at = now() + timedelta(seconds=backoff(job.attempt_count - job.retry_base))
    else:
        transition(s, job, "failed", reason=reason)
        job.completed_at = now()
    job.lease_token = None
    job.lease_until = None
    job.worker_id = None


def finish(
    job_id: str, token: str, result: dict[str, Any] | None = None, error: str | None = None
) -> bool:
    with Session.begin() as s:
        job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job.status != "running" or job.lease_token != token or job.lease_until <= now():
            return False
        if error:
            fail_locked(s, job, error)
        else:
            transition(s, job, "completed")
            job.result, job.error_message, job.completed_at = result, None, now()
            attempt = s.scalar(select(Attempt).where(Attempt.lease_token == token))
            attempt.status, attempt.completed_at = "completed", now()
            attempt.duration = (now() - attempt.started_at).total_seconds()
            job.lease_token = job.lease_until = job.worker_id = None
        return True


def reconcile() -> None:
    with Session.begin() as s:
        expired = s.scalars(
            select(Job)
            .where(Job.status == "running", Job.lease_until <= func.now())
            .limit(500)
            .with_for_update(skip_locked=True)
        ).all()
        for job in expired:
            fail_locked(s, job, "Processing lease expired", crash=True)
        retries = s.scalars(
            select(Job)
            .where(Job.status == "retrying", Job.scheduled_at <= func.now())
            .limit(500)
            .with_for_update(skip_locked=True)
        ).all()
        for job in retries:
            transition(s, job, "pending")
    # Scan all eligible rows in bounded batches, avoiding starvation beyond a fixed LIMIT.
    cursor = ""
    while True:
        with Session() as s:
            jobs = s.scalars(
                select(Job)
                .where(Job.status == "pending", Job.scheduled_at <= func.now(), Job.id > cursor)
                .order_by(Job.id)
                .limit(500)
            ).all()
        if not jobs:
            break
        if not publish(jobs):
            break
        cursor = jobs[-1].id
