import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC (SQLite and Postgres behave the same)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


# Request lifecycle:
#   queued    -> waiting for a worker (attempt_count > 0 means a retry is scheduled)
#   running   -> claimed by a worker
#   succeeded -> got a status < 400
#   failed    -> non-retryable failure (e.g. 404, TLS error, blocked target)
#   dead      -> retryable failure that exhausted max_attempts: the dead-letter queue
STATUSES = ("queued", "running", "succeeded", "failed", "dead")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    replay_of: Mapped[str | None] = mapped_column(String(32), index=True)

    method: Mapped[str] = mapped_column(String(8))
    url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255), index=True)
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    body: Mapped[str | None] = mapped_column(Text)

    timeout_s: Mapped[float] = mapped_column(Float, default=10.0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    backoff_base_s: Mapped[float] = mapped_column(Float, default=1.0)
    backoff_max_s: Mapped[float] = mapped_column(Float, default=60.0)

    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error_kind: Mapped[str | None] = mapped_column(String(32))
    last_latency_ms: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="request", order_by="Attempt.number", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_requests_claim", "status", "next_run_at"),)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime)
    latency_ms: Mapped[float] = mapped_column(Float)

    outcome: Mapped[str] = mapped_column(String(8))  # "success" | "failure"
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    will_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_in_s: Mapped[float | None] = mapped_column(Float)

    response_headers: Mapped[dict] = mapped_column(JSON, default=dict)
    response_body: Mapped[str | None] = mapped_column(Text)
    response_bytes: Mapped[int | None] = mapped_column(Integer)

    request: Mapped[Request] = relationship(back_populates="attempts")
