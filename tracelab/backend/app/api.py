import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .models import STATUSES, Request, new_id
from .queue import requeue_dead
from .schemas import Page, RequestCreate, RequestDetail, RequestSummary, RequeueBody
from .security import BlockedTarget, check_url, require_api_key
from .stats import compute_stats

log = logging.getLogger("tracelab.api")

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@public.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


def _fingerprint(payload: RequestCreate) -> str:
    canonical = json.dumps(payload.model_dump(), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _get_or_404(db: Session, request_id: str) -> Request:
    req = db.get(Request, request_id, options=[selectinload(Request.attempts)])
    if req is None:
        raise HTTPException(404, "Request not found")
    return req


@router.post("/requests", response_model=RequestSummary, status_code=202)
def submit_request(
    payload: RequestCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=255),
    db: Session = Depends(get_db),
):
    """Queue an outbound HTTP request. Send `Idempotency-Key` to make retries of this call safe."""
    fingerprint = _fingerprint(payload)

    if idempotency_key:
        existing = db.scalar(select(Request).where(Request.idempotency_key == idempotency_key))
        if existing:
            return _idempotent_hit(existing, fingerprint, response)

    try:
        host = check_url(payload.url, allow_private=get_settings().allow_private_targets)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except BlockedTarget as exc:
        raise HTTPException(422, f"Target blocked: {exc}") from exc

    req = Request(
        idempotency_key=idempotency_key, fingerprint=fingerprint, host=host[:255],
        method=payload.method, url=payload.url, headers=payload.headers, body=payload.body,
        timeout_s=payload.timeout_s, max_attempts=payload.max_attempts,
        backoff_base_s=payload.backoff_base_s, backoff_max_s=payload.backoff_max_s,
    )
    db.add(req)
    try:
        db.commit()
    except IntegrityError:
        # Two identical submissions raced; the unique index picked a winner.
        db.rollback()
        existing = db.scalar(select(Request).where(Request.idempotency_key == idempotency_key))
        if existing is None:
            raise
        return _idempotent_hit(existing, fingerprint, response)
    log.info("request queued", extra={"request_id": req.id, "host": req.host, "method": req.method})
    return req


def _idempotent_hit(existing: Request, fingerprint: str, response: Response) -> Request:
    if existing.fingerprint != fingerprint:
        raise HTTPException(409, "Idempotency-Key was already used with a different request payload")
    response.headers["Idempotent-Replayed"] = "true"
    response.status_code = 200
    return existing


@router.get("/requests", response_model=Page)
def list_requests(
    status: str | None = Query(None, description="queued|running|retrying|succeeded|failed|dead"),
    host: str | None = None,
    q: str | None = Query(None, description="substring match on URL"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    conds = []
    if status == "retrying":
        conds += [Request.status == "queued", Request.attempt_count > 0]
    elif status:
        if status not in STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(STATUSES)} or retrying")
        conds.append(Request.status == status)
        if status == "queued":
            conds.append(Request.attempt_count == 0)
    if host:
        conds.append(Request.host == host)
    if q:
        conds.append(Request.url.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(Request).where(*conds)) or 0
    items = db.scalars(
        select(Request).where(*conds).order_by(Request.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page(items=items, total=total, limit=limit, offset=offset)  # type: ignore[arg-type]


@router.get("/requests/{request_id}", response_model=RequestDetail)
def get_request(request_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, request_id)


@router.post("/requests/{request_id}/replay", response_model=RequestSummary, status_code=202)
def replay_request(request_id: str, db: Session = Depends(get_db)):
    """Send the same request again as a brand new request (fresh attempts, own history)."""
    src = _get_or_404(db, request_id)
    copy = Request(
        id=new_id(), replay_of=src.id, host=src.host, method=src.method, url=src.url,
        headers=dict(src.headers or {}), body=src.body, timeout_s=src.timeout_s,
        max_attempts=src.max_attempts, backoff_base_s=src.backoff_base_s, backoff_max_s=src.backoff_max_s,
    )
    db.add(copy)
    db.commit()
    log.info("request replayed", extra={"request_id": copy.id, "replay_of": src.id})
    return copy


@router.get("/dlq", response_model=Page)
def dead_letters(limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Request).where(Request.status == "dead")) or 0
    items = db.scalars(
        select(Request).where(Request.status == "dead").order_by(Request.completed_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return Page(items=items, total=total, limit=limit, offset=offset)  # type: ignore[arg-type]


@router.post("/dlq/{request_id}/requeue", response_model=RequestSummary, status_code=202)
def requeue(request_id: str, body: RequeueBody | None = None, db: Session = Depends(get_db)):
    """Move a dead-lettered request back onto the queue with extra attempts."""
    req = _get_or_404(db, request_id)
    if req.status != "dead":
        raise HTTPException(409, f"Only dead-lettered requests can be requeued (this one is {req.status})")
    return requeue_dead(db, req, (body or RequeueBody()).extra_attempts)


@router.get("/stats")
def stats(
    window_hours: int = Query(24, ge=1, le=168),
    bucket_minutes: int = Query(60, ge=1, le=1440),
    db: Session = Depends(get_db),
):
    if window_hours * 60 / bucket_minutes > 500:
        raise HTTPException(422, "Too many buckets: increase bucket_minutes or shrink window_hours")
    return compute_stats(db, window_hours, bucket_minutes)


