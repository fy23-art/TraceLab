"""Real HTTP against a local server: submit -> worker retries with backoff -> dashboard data."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.stats import compute_stats
from app.worker import Worker


class Handler(BaseHTTPRequestHandler):
    hits: dict[str, int] = {}

    def do_GET(self):
        n = Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        if self.path == "/flaky":  # fails twice, then works
            status = 503 if n <= 2 else 200
        elif self.path == "/down":
            status = 500
        elif self.path == "/missing":
            status = 404
        elif self.path == "/limited":
            status = 429
        else:
            status = 200
        body = json.dumps({"hit": n}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if status == 429:
            self.send_header("Retry-After", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Handler.hits = {}
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def drain(worker: Worker, timeout=10):
    """Run the worker until the queue is empty (including scheduled retries)."""
    from app import db
    from app.models import Request

    deadline = time.time() + timeout
    while time.time() < deadline:
        worker.run_once()
        s = db.new_session()
        pending = s.query(Request).filter(Request.status.in_(["queued", "running"])).count()
        s.close()
        if pending == 0:
            return
        time.sleep(0.05)
    raise AssertionError("queue did not drain")


FAST = {"backoff_base_s": 0.05, "backoff_max_s": 0.1}


def test_flaky_endpoint_succeeds_after_retries(client, server):
    rid = client.post("/api/requests", json={"url": f"{server}/flaky", "max_attempts": 4, **FAST}).json()["id"]
    drain(Worker())
    detail = client.get(f"/api/requests/{rid}").json()
    assert detail["status"] == "succeeded" and detail["attempt_count"] == 3
    assert [a["status_code"] for a in detail["attempts"]] == [503, 503, 200]
    assert [a["will_retry"] for a in detail["attempts"]] == [True, True, False]
    assert detail["attempts"][0]["error_kind"] == "unavailable"
    assert detail["attempts"][2]["response_body"] == '{"hit": 3}'


def test_permanent_failure_lands_in_dlq_and_can_be_requeued(client, server):
    rid = client.post("/api/requests", json={"url": f"{server}/down", "max_attempts": 2, **FAST}).json()["id"]
    drain(Worker())
    detail = client.get(f"/api/requests/{rid}").json()
    assert detail["status"] == "dead" and detail["attempt_count"] == 2
    assert detail["diagnosis"]["kind"] == "server_error" and detail["diagnosis"]["suggestion"]
    assert client.get("/api/dlq").json()["total"] == 1

    assert client.post(f"/api/dlq/{rid}/requeue", json={"extra_attempts": 1}).status_code == 202
    drain(Worker())
    detail = client.get(f"/api/requests/{rid}").json()
    assert detail["status"] == "dead" and detail["attempt_count"] == 3


def test_client_errors_are_not_retried(client, server):
    rid = client.post("/api/requests", json={"url": f"{server}/missing", **FAST}).json()["id"]
    drain(Worker())
    detail = client.get(f"/api/requests/{rid}").json()
    assert detail["status"] == "failed" and detail["attempt_count"] == 1
    assert detail["diagnosis"]["kind"] == "not_found"
    assert Handler.hits["/missing"] == 1


def test_replay_of_a_failed_request_runs_again(client, server):
    rid = client.post("/api/requests", json={"url": f"{server}/missing", **FAST}).json()["id"]
    drain(Worker())
    copy = client.post(f"/api/requests/{rid}/replay").json()
    drain(Worker())
    assert client.get(f"/api/requests/{copy['id']}").json()["attempt_count"] == 1
    assert Handler.hits["/missing"] == 2


def test_connection_refused_is_diagnosed(client):
    rid = client.post("/api/requests", json={"url": "http://127.0.0.1:1/", "max_attempts": 1, **FAST}).json()["id"]
    drain(Worker())
    detail = client.get(f"/api/requests/{rid}").json()
    assert detail["diagnosis"]["kind"] == "connection_refused" and detail["status"] == "dead"


def test_timeout_is_diagnosed(client):
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)  # accepts connections in the kernel backlog but never answers
    port = sock.getsockname()[1]
    rid = client.post("/api/requests", json={"url": f"http://127.0.0.1:{port}/", "timeout_s": 0.3,
                                             "max_attempts": 1}).json()["id"]
    drain(Worker())
    sock.close()
    assert client.get(f"/api/requests/{rid}").json()["diagnosis"]["kind"] == "read_timeout"


def test_stats_reflect_traffic(client, server):
    for path in ("/ok", "/ok", "/missing"):
        client.post("/api/requests", json={"url": f"{server}{path}", **FAST})
    drain(Worker())
    from app import db

    s = db.new_session()
    stats = compute_stats(s, window_hours=1, bucket_minutes=5)
    s.close()
    assert stats["attempts"]["total"] == 3 and stats["attempts"]["failure"] == 1
    assert stats["failure_kinds"] == [{"kind": "not_found", "count": 1}]
    assert stats["latency_ms"]["p95"] is not None
    assert stats["top_hosts"][0]["attempts"] == 3
    assert sum(b["success"] + b["failure"] for b in stats["timeseries"]) == 3


def test_retries_reuse_one_idempotency_key_for_unsafe_methods(client):
    from app.executor import outbound_headers

    first = outbound_headers("POST", {"Accept": "x"}, "abc123", 1)
    retry = outbound_headers("POST", {"Accept": "x"}, "abc123", 2)
    assert first["Idempotency-Key"] == retry["Idempotency-Key"] == "abc123"
    assert (first["X-TraceLab-Attempt"], retry["X-TraceLab-Attempt"]) == ("1", "2")
    assert "Idempotency-Key" not in outbound_headers("GET", {}, "abc123", 1)
    mine = outbound_headers("POST", {"idempotency-key": "order-7"}, "abc123", 1)
    assert mine["idempotency-key"] == "order-7" and "Idempotency-Key" not in mine
