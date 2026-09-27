import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from redis import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import Attempt, Event, Job, Session, Worker, now
from app.queue import redis
from app.service import Conflict, submit, transition
from app.tasks import validate


class Submission(BaseModel):
    task_type: str
    payload: dict
    priority: Literal["high", "normal", "low"] = "normal"
    max_retries: int = Field(default=3, ge=0, le=20)
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone")
        return value

    @model_validator(mode="after")
    def payload_valid(self):
        self.payload = validate(self.task_type, self.payload)
        return self


DEMO_KEY = "public-demo"


def auth(x_api_key: str = Header(default="")):
    if secrets.compare_digest(x_api_key.encode(), settings.api_key.encode()):
        return "owner"
    if settings.demo_mode and x_api_key == DEMO_KEY:
        return "demo"
    raise HTTPException(401, "Invalid API key")


def owner_only(access: str = Depends(auth)):
    if access != "owner":
        raise HTTPException(403, "Owner API key required")


def limit_demo_submission(data: "Submission") -> None:
    if data.task_type not in {
        "fibonacci",
        "long_running",
        "document_processing",
        "generate_report",
        "simulated_failure",
    }:
        raise HTTPException(403, "Task unavailable in the public demo")
    p = data.payload
    if (
        data.max_retries > 2
        or (data.scheduled_at and data.scheduled_at > now() + timedelta(days=1))
        or (data.task_type == "fibonacci" and p["n"] > 1000)
        or (data.task_type == "long_running" and p["seconds"] > 5)
        or (data.task_type == "document_processing" and len(p["text"]) > 5000)
        or (data.task_type == "generate_report" and len(p["rows"]) > 25)
        or (data.task_type == "simulated_failure" and p["failures"] > 2)
    ):
        raise HTTPException(422, "Public demo task exceeds its limits")
    # One atomic Redis quota shared across all visitors and API instances.
    key = "queuemaster:demo:" + datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        count = redis.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],172800) end; return n",
            1,
            key,
        )
    except RedisError:
        raise HTTPException(503, "Demo quota unavailable") from None
    if count > settings.demo_daily_limit:
        raise HTTPException(429, "Public demo daily limit reached; try tomorrow")


app = FastAPI(title="QueueMaster", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "index.html")


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > settings.request_limit:
                return await JSONResponse(
                    {"error": {"code": 413, "message": "Request too large"}}, status_code=413
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc):
    return JSONResponse(
        {"error": {"code": exc.status_code, "message": exc.detail}}, status_code=exc.status_code
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc):
    return JSONResponse(
        {
            "error": {
                "code": 422,
                "message": "Invalid request",
                "details": [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()],
            }
        },
        status_code=422,
    )


@app.exception_handler(Conflict)
async def conflict(request: Request, exc):
    return JSONResponse({"error": {"code": 409, "message": str(exc)}}, status_code=409)


@app.exception_handler(SQLAlchemyError)
async def db_error(request: Request, exc):
    return JSONResponse(
        {
            "error": {
                "code": 503,
                "message": "Database unavailable; retry with the same idempotency key",
            }
        },
        status_code=503,
    )


def encoded(row):
    return jsonable_encoder(
        {
            c.name: getattr(row, c.name)
            for c in row.__table__.columns
            if c.name not in {"request_hash", "lease_token", "idempotency_key"}
        }
    )


def get_job(s, job_id, lock=False):
    query = select(Job).where(Job.id == job_id)
    row = s.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Job not found")
    return row


@app.get("/health")
def health():
    return {"status": "alive"}


@app.get("/demo-config", include_in_schema=False)
def demo_config():
    return {"enabled": settings.demo_mode}


@app.get("/ready")
def ready():
    try:
        with Session() as s:
            s.execute(text("SELECT 1"))
        redis.ping()
    except (SQLAlchemyError, RedisError):
        raise HTTPException(503, "Dependency unavailable") from None
    return {"status": "ready"}


PREFIX = "/api/v1"
AUTH = [Depends(auth)]


@app.post(PREFIX + "/jobs", dependencies=AUTH)
def create(
    data: Submission,
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=128),
    access: str = Depends(auth),
):
    if access == "demo":
        limit_demo_submission(data)
    job, created = submit(data, idempotency_key)
    return JSONResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "message": "Job submitted successfully" if created else "Existing submission",
        },
        status_code=201 if created else 200,
    )


@app.get(PREFIX + "/jobs", dependencies=AUTH)
def jobs(
    status: Literal["pending", "running", "retrying", "completed", "failed", "cancelled"]
    | None = None,
    task_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with Session() as s:
        query = select(Job)
        if status:
            query = query.where(Job.status == status)
        if task_type:
            query = query.where(Job.task_type == task_type)
        total = s.scalar(select(func.count()).select_from(query.subquery()))
        rows = s.scalars(query.order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset))
        return {
            "items": [encoded(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.get(PREFIX + "/dead-letter", dependencies=AUTH)
def dead_letter(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return jobs(status="failed", task_type=None, limit=limit, offset=offset)


@app.get(PREFIX + "/jobs/{job_id}", dependencies=AUTH)
def job_detail(job_id: str):
    with Session() as s:
        return encoded(get_job(s, job_id))


@app.get(PREFIX + "/jobs/{job_id}/result", dependencies=AUTH)
def result(job_id: str):
    with Session() as s:
        job = get_job(s, job_id)
        if job.status != "completed":
            raise HTTPException(409, f"Result unavailable: {job.status}")
        return {"job_id": job.id, "result": job.result}


@app.get(PREFIX + "/jobs/{job_id}/attempts", dependencies=AUTH)
def attempts(job_id: str):
    with Session() as s:
        get_job(s, job_id)
        return [
            encoded(a)
            for a in s.scalars(
                select(Attempt).where(Attempt.job_id == job_id).order_by(Attempt.attempt_number)
            )
        ]


@app.get(PREFIX + "/jobs/{job_id}/events", dependencies=AUTH)
def events(job_id: str):
    with Session() as s:
        get_job(s, job_id)
        return [
            encoded(e)
            for e in s.scalars(
                select(Event).where(Event.job_id == job_id).order_by(Event.timestamp)
            )
        ]


@app.post(PREFIX + "/jobs/{job_id}/cancel", dependencies=[Depends(owner_only)])
def cancel(job_id: str):
    with Session.begin() as s:
        job = get_job(s, job_id, True)
        transition(s, job, "cancelled")
        job.completed_at = now()
        return encoded(job)


@app.post(PREFIX + "/jobs/{job_id}/retry", dependencies=[Depends(owner_only)])
def retry(job_id: str):
    with Session.begin() as s:
        job = get_job(s, job_id, True)
        if job.status != "failed":
            raise Conflict("Only dead-letter jobs may be manually retried")
        transition(s, job, "pending", manual=True)
        job.retry_base = job.attempt_count
        job.scheduled_at, job.completed_at, job.error_message = now(), None, None
        return encoded(job)


@app.get(PREFIX + "/workers", dependencies=AUTH)
def workers():
    with Session() as s:
        return [
            dict(
                encoded(w),
                active=w.status != "stopped"
                and w.last_heartbeat > now() - timedelta(seconds=settings.lease_seconds),
            )
            for w in s.scalars(select(Worker).order_by(Worker.started_at.desc()).limit(200))
        ]


@app.get(PREFIX + "/stats", dependencies=AUTH)
def stats():
    with Session() as s:
        counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        active = s.scalar(
            select(func.count())
            .select_from(Worker)
            .where(
                Worker.status != "stopped",
                Worker.last_heartbeat > now() - timedelta(seconds=settings.lease_seconds),
            )
        )
        retried = s.scalar(select(func.count()).select_from(Job).where(Job.attempt_count > 1))
        duration = s.scalar(select(func.avg(Attempt.duration)).where(Attempt.status == "completed"))
    try:
        depth = redis.zcard(settings.queue_key)
    except RedisError:
        depth = None
    return {
        "total_submitted": sum(counts.values()),
        **{
            k: counts.get(k, 0)
            for k in ("pending", "running", "retrying", "completed", "failed", "cancelled")
        },
        "retried_jobs": retried,
        "active_workers": active,
        "average_execution_seconds": duration,
        "queue_depth": depth,
    }
