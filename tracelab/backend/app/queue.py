"""A small, durable job queue on top of the requests table.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres plus a compare-and-swap UPDATE so it is
also safe on SQLite. Crashed workers are handled by leases: a `running` request whose lock is older
than the lease is picked up again.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from .models import Attempt, Request, utcnow


@dataclass
class AttemptResult:
    started_at: datetime
    finished_at: datetime
    latency_ms: float
    success: bool
    status_code: int | None = None
    error_kind: str | None = None
    error_message: str | None = None
    retryable: bool = False
    retry_after_s: float | None = None
    response_headers: dict | None = None
    response_body: str | None = None
    response_bytes: int | None = None


def compute_backoff(
    attempt: int,
    base_s: float,
    cap_s: float,
    retry_after_s: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Exponential backoff with "equal jitter": half fixed, half random, capped.

    `attempt` is the attempt that just failed (1-based). Retry-After from the server wins if longer.
    """
    rng = rng or random
    ceiling = min(cap_s, base_s * 2 ** (attempt - 1))
    delay = ceiling / 2 + rng.uniform(0, ceiling / 2)
    if retry_after_s:
        delay = max(delay, min(retry_after_s, cap_s))
    return delay


def claim_next(db: Session, worker_id: str, lease_s: int, now: datetime | None = None) -> Request | None:
    now = now or utcnow()
    stale_before = now - timedelta(seconds=lease_s)
    while True:
        stmt = (
            select(Request)
            .where(
                or_(
                    and_(Request.status == "queued", Request.next_run_at <= now),
                    and_(Request.status == "running", Request.locked_at < stale_before),
                )
            )
            .order_by(Request.next_run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        req = db.execute(stmt).scalar_one_or_none()
        if req is None:
            db.rollback()
            return None

        if req.status == "running" and req.attempt_count >= req.max_attempts:
            # The worker died during the final attempt. Do not run it again; send it to the DLQ.
            db.execute(
                update(Request)
                .where(Request.id == req.id, Request.attempt_count == req.attempt_count)
                .values(status="dead", last_error_kind="worker_lost", locked_by=None,
                        locked_at=None, completed_at=now, updated_at=now)
            )
            db.commit()
            continue

        claimed = db.execute(
            update(Request)
            .where(Request.id == req.id, Request.status == req.status,
                   Request.attempt_count == req.attempt_count)
            .values(status="running", locked_by=worker_id, locked_at=now,
                    attempt_count=req.attempt_count + 1, updated_at=now)
        )
        db.commit()
        if claimed.rowcount == 1:
            db.refresh(req)
            return req
        # Lost the race to another worker; look again.


def record_attempt(db: Session, req: Request, result: AttemptResult, rng: random.Random | None = None) -> Attempt:
    """Store the attempt and move the request to its next state."""
    now = utcnow()
    will_retry, retry_in = False, None

    if result.success:
        req.status, req.completed_at = "succeeded", now
    elif result.retryable and req.attempt_count < req.max_attempts:
        retry_in = compute_backoff(req.attempt_count, req.backoff_base_s, req.backoff_max_s,
                                   result.retry_after_s, rng)
        will_retry = True
        req.status = "queued"
        req.next_run_at = now + timedelta(seconds=retry_in)
    elif result.retryable:
        req.status, req.completed_at = "dead", now
    else:
        req.status, req.completed_at = "failed", now

    attempt = Attempt(
        request_id=req.id, number=req.attempt_count,
        started_at=result.started_at, finished_at=result.finished_at, latency_ms=result.latency_ms,
        outcome="success" if result.success else "failure",
        status_code=result.status_code, error_kind=result.error_kind, error_message=result.error_message,
        retryable=result.retryable, will_retry=will_retry, retry_in_s=retry_in,
        response_headers=result.response_headers or {}, response_body=result.response_body,
        response_bytes=result.response_bytes,
    )
    db.add(attempt)
    req.last_status_code = result.status_code
    req.last_error_kind = result.error_kind
    req.last_latency_ms = result.latency_ms
    req.locked_by = req.locked_at = None
    db.commit()
    return attempt


def requeue_dead(db: Session, req: Request, extra_attempts: int) -> Request:
    """Give a dead-lettered request more attempts, starting immediately."""
    req.status = "queued"
    req.max_attempts = req.attempt_count + extra_attempts
    req.next_run_at = utcnow()
    req.completed_at = None
    db.commit()
    return req



def queue_depth(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    rows = dict(db.execute(select(Request.status, func.count()).group_by(Request.status)).all())
    scheduled = db.scalar(
        select(func.count()).where(Request.status == "queued", Request.next_run_at > now)
    ) or 0
    queued = rows.get("queued", 0)
    return {
        "ready": queued - scheduled,
        "scheduled": scheduled,
        "running": rows.get("running", 0),
        "dead": rows.get("dead", 0),
        "failed": rows.get("failed", 0),
        "succeeded": rows.get("succeeded", 0),
    }
