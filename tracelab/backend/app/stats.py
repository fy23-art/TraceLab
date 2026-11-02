"""Latency and error-rate analytics. Percentiles are computed in Python so SQLite and Postgres agree."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attempt, Request, utcnow
from .queue import queue_depth

MAX_ROWS = 50_000


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile (same as numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _latency(values: list[float]) -> dict:
    return {
        "avg": sum(values) / len(values) if values else None,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def compute_stats(db: Session, window_hours: int = 24, bucket_minutes: int = 60, now: datetime | None = None) -> dict:
    now = now or utcnow()
    since = now - timedelta(hours=window_hours)
    bucket = timedelta(minutes=bucket_minutes)

    rows = db.execute(
        select(Attempt.started_at, Attempt.latency_ms, Attempt.outcome, Attempt.error_kind, Request.host)
        .join(Request, Request.id == Attempt.request_id)
        .where(Attempt.started_at >= since)
        .order_by(Attempt.started_at.desc())
        .limit(MAX_ROWS)
    ).all()

    # Buckets are aligned to `since`, and every bucket is emitted so charts have no gaps.
    n_buckets = max(1, int((now - since) / bucket) + 1)
    buckets: list[dict] = [{"lat": [], "ok": 0, "fail": 0} for _ in range(n_buckets)]
    by_host: dict[str, dict] = defaultdict(lambda: {"lat": [], "ok": 0, "fail": 0})
    kinds: Counter[str] = Counter()
    all_lat: list[float] = []
    ok = fail = 0

    for started_at, latency, outcome, kind, host in rows:
        idx = min(n_buckets - 1, max(0, int((started_at - since) / bucket)))
        h = by_host[host]
        success = outcome == "success"
        for agg in (buckets[idx], h):
            agg["ok" if success else "fail"] += 1
            agg["lat"].append(latency)
        all_lat.append(latency)
        if success:
            ok += 1
        else:
            fail += 1
            kinds[kind or "unknown"] += 1

    total = ok + fail
    series = [
        {
            "ts": (since + bucket * i).isoformat(),
            "success": b["ok"],
            "failure": b["fail"],
            "p50": percentile(b["lat"], 50),
            "p95": percentile(b["lat"], 95),
        }
        for i, b in enumerate(buckets)
    ]
    hosts = sorted(by_host.items(), key=lambda kv: kv[1]["ok"] + kv[1]["fail"], reverse=True)[:10]

    return {
        "window_hours": window_hours,
        "bucket_minutes": bucket_minutes,
        "attempts": {
            "total": total, "success": ok, "failure": fail,
            "success_rate": ok / total if total else None,
            "error_rate": fail / total if total else None,
        },
        "latency_ms": _latency(all_lat),
        "queue": queue_depth(db, now),
        "failure_kinds": [{"kind": k, "count": c} for k, c in kinds.most_common()],
        "top_hosts": [
            {
                "host": host,
                "attempts": h["ok"] + h["fail"],
                "error_rate": h["fail"] / (h["ok"] + h["fail"]),
                "p95": percentile(h["lat"], 95),
            }
            for host, h in hosts
        ],
        "timeseries": series,
    }
