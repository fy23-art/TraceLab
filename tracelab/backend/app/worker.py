"""Worker process: claims due requests, sends them, records every attempt."""

import logging
import os
import signal
import socket
import threading
import time

import httpx

from . import db
from .config import Settings, get_settings
from .executor import RequestSnapshot, execute, outbound_headers
from .logging_setup import configure_logging
from .queue import claim_next, record_attempt

log = logging.getLogger("tracelab.worker")


class Worker:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None,
                 worker_id: str | None = None):
        self.settings = settings or get_settings()
        self.transport = transport
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{threading.get_ident() % 10000}"

    def run_once(self) -> bool:
        """Process at most one request. Returns False when nothing was due."""
        session = db.new_session()
        try:
            req = claim_next(session, self.worker_id, self.settings.lease_seconds)
            if req is None:
                return False
            attempt_no = req.attempt_count
            headers = outbound_headers(req.method, dict(req.headers or {}), req.id, attempt_no)
            snap = RequestSnapshot(req.method, req.url, headers, req.body, req.timeout_s)
            session.commit()  # release the connection's transaction while we do network I/O
            result = execute(snap, self.settings, self.transport)
            attempt = record_attempt(session, req, result)
            log.info(
                "attempt finished",
                extra={"request_id": req.id, "attempt": attempt_no, "outcome": attempt.outcome,
                       "status_code": attempt.status_code, "error_kind": attempt.error_kind,
                       "latency_ms": round(attempt.latency_ms, 1), "will_retry": attempt.will_retry,
                       "request_status": req.status, "host": req.host},
            )
            return True
        finally:
            session.close()

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                if not self.run_once():
                    stop.wait(self.settings.poll_interval_s)
            except Exception:  # noqa: BLE001 - keep the loop alive across DB blips
                log.exception("worker loop error")
                stop.wait(2)


def start_threads(settings: Settings, stop: threading.Event) -> list[threading.Thread]:
    threads = [
        threading.Thread(target=Worker(settings).run_forever, args=(stop,), name=f"worker-{i}", daemon=True)
        for i in range(settings.worker_concurrency)
    ]
    for t in threads:
        t.start()
    return threads


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    db.init()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    threads = start_threads(settings, stop)
    log.info("worker started", extra={"concurrency": settings.worker_concurrency})
    while not stop.is_set():
        time.sleep(0.5)
    for t in threads:
        t.join(timeout=settings.poll_interval_s + 35)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
