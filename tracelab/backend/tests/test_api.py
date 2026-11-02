import pytest

from app.config import get_settings

BODY = {"method": "GET", "url": "http://svc.test/ping"}


def test_submit_returns_202_and_queues(client):
    r = client.post("/api/requests", json=BODY)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "queued" and data["state"] == "queued" and data["host"] == "svc.test"
    assert client.get(f"/api/requests/{data['id']}").json()["attempts"] == []


@pytest.mark.parametrize("bad", [
    {"url": "ftp://x.test"}, {"url": "http://x.test", "method": "TRACE"},
    {"url": "http://x.test", "max_attempts": 0}, {"url": "http://x.test", "timeout_s": 999},
    {"url": "http://x.test", "backoff_base_s": 10, "backoff_max_s": 1},
    {"url": "http://x.test", "headers": {"Bad Header": "x"}},
])
def test_validation_rejects_bad_input(client, bad):
    assert client.post("/api/requests", json=bad).status_code == 422


def test_private_target_rejected_when_not_allowed(client, monkeypatch):
    monkeypatch.setenv("TRACELAB_ALLOW_PRIVATE_TARGETS", "false")
    get_settings.cache_clear()
    r = client.post("/api/requests", json={"url": "http://169.254.169.254/"})
    assert r.status_code == 422 and "blocked" in r.json()["detail"].lower()


def test_idempotency_key_dedupes(client):
    h = {"Idempotency-Key": "order-42"}
    first = client.post("/api/requests", json=BODY, headers=h)
    second = client.post("/api/requests", json=BODY, headers=h)
    assert first.status_code == 202 and second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]
    assert client.get("/api/requests").json()["total"] == 1


def test_idempotency_key_reuse_with_different_payload_conflicts(client):
    h = {"Idempotency-Key": "k1"}
    client.post("/api/requests", json=BODY, headers=h)
    r = client.post("/api/requests", json={**BODY, "url": "http://svc.test/other"}, headers=h)
    assert r.status_code == 409


def test_secrets_are_redacted_in_responses(client):
    r = client.post("/api/requests", json={**BODY, "headers": {"Authorization": "Bearer s3cret", "Accept": "x"}})
    detail = client.get(f"/api/requests/{r.json()['id']}").json()
    assert detail["headers"] == {"Authorization": "***", "Accept": "x"}


def test_list_filters_and_pagination(client):
    ids = [client.post("/api/requests", json={"url": f"http://h{i % 2}.test/p{i}"}).json()["id"] for i in range(5)]
    page = client.get("/api/requests?limit=2").json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["items"][0]["id"] == ids[-1]
    assert client.get("/api/requests?host=h0.test").json()["total"] == 3
    assert client.get("/api/requests?q=p3").json()["total"] == 1
    assert client.get("/api/requests?status=bogus").status_code == 422


def test_unknown_request_404(client):
    assert client.get("/api/requests/nope").status_code == 404
    assert client.post("/api/requests/nope/replay").status_code == 404


def test_replay_creates_linked_copy(client):
    src = client.post("/api/requests", json={**BODY, "headers": {"X-Test": "1"}}).json()
    copy = client.post(f"/api/requests/{src['id']}/replay")
    assert copy.status_code == 202
    assert copy.json()["id"] != src["id"] and copy.json()["replay_of"] == src["id"]
    assert client.get(f"/api/requests/{copy.json()['id']}").json()["headers"] == {"X-Test": "1"}


def test_requeue_only_works_on_dead_requests(client):
    rid = client.post("/api/requests", json=BODY).json()["id"]
    assert client.post(f"/api/dlq/{rid}/requeue").status_code == 409
    assert client.get("/api/dlq").json()["total"] == 0


def test_stats_shape_on_empty_db(client):
    s = client.get("/api/stats?window_hours=6&bucket_minutes=60").json()
    assert s["attempts"]["total"] == 0 and s["attempts"]["error_rate"] is None
    assert len(s["timeseries"]) >= 6 and s["queue"]["ready"] == 0
    assert client.get("/api/stats?window_hours=168&bucket_minutes=1").status_code == 422


def test_api_key_protects_api_but_not_health(client, monkeypatch):
    monkeypatch.setenv("TRACELAB_API_KEY", "letmein")
    get_settings.cache_clear()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/requests").status_code == 401
    assert client.get("/api/requests", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/requests", headers={"X-API-Key": "letmein"}).status_code == 200
