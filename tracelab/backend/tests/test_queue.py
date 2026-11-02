import random
from datetime import timedelta

from app.models import Request, utcnow
from app.queue import AttemptResult, claim_next, compute_backoff, queue_depth, record_attempt, requeue_dead


def make_request(session, **kw):
    defaults = dict(method="GET", url="http://svc.test/x", host="svc.test", max_attempts=3,
                    backoff_base_s=1, backoff_max_s=30)
    req = Request(**{**defaults, **kw})
    session.add(req)
    session.commit()
    return req


def result(success=False, retryable=True, status=500, kind="server_error", **kw):
    now = utcnow()
    return AttemptResult(started_at=now, finished_at=now, latency_ms=12.0, success=success,
                         status_code=status, error_kind=None if success else kind,
                         retryable=retryable, **kw)


def test_backoff_grows_exponentially_with_jitter_and_cap():
    rng = random.Random(1)
    for attempt, ceiling in [(1, 1), (2, 2), (3, 4), (4, 8), (10, 30)]:
        for _ in range(50):
            d = compute_backoff(attempt, 1, 30, rng=rng)
            assert ceiling / 2 <= d <= ceiling


def test_backoff_honors_retry_after_but_respects_cap():
    assert compute_backoff(1, 1, 30, retry_after_s=20) == 20
    assert compute_backoff(1, 1, 30, retry_after_s=999) == 30


def test_claim_marks_running_and_counts_attempt(session):
    req = make_request(session)
    claimed = claim_next(session, "w1", 60)
    assert claimed.id == req.id and claimed.status == "running" and claimed.attempt_count == 1
    assert claim_next(session, "w2", 60) is None  # already taken


def test_future_requests_are_not_claimed(session):
    make_request(session, next_run_at=utcnow() + timedelta(minutes=5))
    assert claim_next(session, "w1", 60) is None


def test_oldest_due_request_first(session):
    now = utcnow()
    late = make_request(session, next_run_at=now - timedelta(seconds=1))
    early = make_request(session, next_run_at=now - timedelta(seconds=30))
    assert claim_next(session, "w1", 60).id == early.id
    assert claim_next(session, "w1", 60).id == late.id


def test_success_completes(session):
    make_request(session)
    req = claim_next(session, "w", 60)
    record_attempt(session, req, result(success=True, status=200))
    assert req.status == "succeeded" and req.completed_at and req.locked_by is None


def test_retryable_failure_is_rescheduled_with_backoff(session):
    make_request(session)
    req = claim_next(session, "w", 60)
    attempt = record_attempt(session, req, result(), rng=random.Random(0))
    assert req.status == "queued" and attempt.will_retry
    assert req.next_run_at > utcnow() and 0.5 <= attempt.retry_in_s <= 1.0
    assert claim_next(session, "w", 60) is None  # not due yet
    assert queue_depth(session)["scheduled"] == 1


def test_exhausted_retries_go_to_dead_letter_queue(session):
    make_request(session, max_attempts=2)
    for _ in range(2):
        req = claim_next(session, "w", 60, now=utcnow() + timedelta(hours=1))
        record_attempt(session, req, result())
    assert req.status == "dead" and req.attempt_count == 2
    assert queue_depth(session)["dead"] == 1


def test_non_retryable_failure_is_final(session):
    make_request(session)
    req = claim_next(session, "w", 60)
    record_attempt(session, req, result(status=404, kind="not_found", retryable=False))
    assert req.status == "failed" and req.attempt_count == 1


def test_requeue_dead_adds_attempts(session):
    make_request(session, max_attempts=1)
    req = claim_next(session, "w", 60)
    record_attempt(session, req, result())
    assert req.status == "dead"
    requeue_dead(session, req, extra_attempts=3)
    assert req.status == "queued" and req.max_attempts == 4
    again = claim_next(session, "w", 60)
    assert again.attempt_count == 2


def test_stale_lease_is_reclaimed(session):
    req = make_request(session)
    claim_next(session, "crashed-worker", 60)
    assert claim_next(session, "w2", 60) is None  # lease still valid
    later = utcnow() + timedelta(seconds=120)
    reclaimed = claim_next(session, "w2", 60, now=later)
    assert reclaimed.id == req.id and reclaimed.locked_by == "w2" and reclaimed.attempt_count == 2


def test_worker_that_died_on_final_attempt_goes_to_dlq(session):
    req = make_request(session, max_attempts=1)
    claim_next(session, "crashed-worker", 60)
    assert claim_next(session, "w2", 60, now=utcnow() + timedelta(seconds=120)) is None
    session.refresh(req)
    assert req.status == "dead" and req.last_error_kind == "worker_lost"


def test_concurrent_workers_never_claim_the_same_request_twice(session):
    import threading

    from app import db

    for _ in range(40):
        session.add(Request(method="GET", url="http://svc.test/x", host="svc.test"))
    session.commit()

    claimed, lock = [], threading.Lock()

    def work(name):
        s = db.new_session()
        while (req := claim_next(s, name, 60)) is not None:
            with lock:
                claimed.append(req.id)
        s.close()

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(claimed) == 40 and len(set(claimed)) == 40
