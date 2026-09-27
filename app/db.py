from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_base: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workers.id"))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_jobs_due", "status", "scheduled_at"),
        Index("ix_jobs_lease", "status", "lease_until"),
        Index("ix_jobs_created", "created_at", "id"),
        CheckConstraint(
            "status IN ('pending','running','retrying','completed','failed','cancelled')"
        ),
        CheckConstraint("priority BETWEEN 0 AND 2 AND max_retries >= 0 AND attempt_count >= 0"),
    )


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="idle")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str] = mapped_column(String(36), unique=True)
    duration: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("job_id", "attempt_number"),)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Counter(Base):
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Effect(Base):
    __tablename__ = "effects"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    result: Mapped[dict] = mapped_column(JSON)


engine = create_engine(settings.database_url, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)
