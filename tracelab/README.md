# TraceLab

**API reliability and replay platform.** Submit HTTP requests, let TraceLab deliver them with retries and
exponential backoff, replay anything that failed, and see *why* it failed.

- **REST API** (FastAPI) with request validation and Postgres storage
- **Durable job queue** in Postgres: retry policies, exponential backoff with jitter, `Retry-After` support, dead-letter queue, crash recovery
- **Idempotency keys** on submission, and a stable `Idempotency-Key` forwarded on every retry of a write
- **Failure diagnosis**: each failure is classified (DNS, refused, timeout, TLS, 429, 5xx, ...) with an explanation and a suggested fix
- **React dashboard**: latency percentiles, error rates, per-host health, request history, and an attempt waterfall that shows retries and backoff waits
- **Tests, CI, structured logs, Docker Compose**, and an SSRF guard so a public demo cannot be used to probe your network

```
 browser ──► nginx (web) ──► FastAPI (api) ──► Postgres ◄── worker(s)
                 static React        │             requests + attempts      │
                                     └─ validates, stores, enqueues         └─ claims due requests,
                                        serves stats                           sends them, records attempts
```

## Quick start (Docker)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, and TRACELAB_API_KEY for anything public
docker compose up -d --build
open http://localhost:8080    # dashboard
open http://localhost:8000/docs   # interactive API docs (local only)
python scripts/seed_demo.py   # optional: queue ~60 realistic requests (uses httpbin.org)
```

In the dashboard, **Send a request** has one-click examples: a request that succeeds, one that fails and
retries, one that times out, and one that is rejected (404) and not retried.

## Local development

```bash
# backend (Python 3.12). SQLite by default, no database to install.
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
make -C .. dev-api          # API on :8000
make -C .. dev-worker       # worker (separate terminal)

# frontend
cd frontend && npm install && npm run dev    # http://localhost:5173, proxies /api to :8000
```

Tests and lint:

```bash
cd backend && ruff check . && python -m pytest -q          # SQLite
TRACELAB_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/test python -m pytest -q   # Postgres
cd frontend && npm run build                                # type-check + bundle
```

The suite covers the classifier, the SSRF guard, queue semantics (backoff bounds, leases, DLQ, concurrent
claiming by 8 threads), the whole HTTP API, and end-to-end runs against a local server that fails on purpose.

## API

All routes are under `/api`. If `TRACELAB_API_KEY` is set, send it as `X-API-Key` (except `/api/health`).

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/requests` | Queue an outbound request. Returns `202`. Honors an `Idempotency-Key` header. |
| `GET` | `/requests` | List and filter: `status` (queued, retrying, running, succeeded, failed, dead), `host`, `q`, `limit`, `offset`. |
| `GET` | `/requests/{id}` | Full detail: every attempt, response preview, and the diagnosis. |
| `POST` | `/requests/{id}/replay` | Send the same request again as a new request linked to the original. |
| `GET` | `/dlq` | Dead-lettered requests. |
| `POST` | `/dlq/{id}/requeue` | Give a dead request `extra_attempts` more tries. |
| `GET` | `/stats` | Success and error rates, p50/p95/p99, time series, failure kinds, per-host breakdown, queue depth. |
| `GET` | `/health` | Liveness and database check. |

```bash
curl -X POST localhost:8000/api/requests \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: order-1042' \
  -d '{"method":"POST","url":"https://api.example.com/orders","body":"{\"id\":1042}",
       "headers":{"Content-Type":"application/json"},
       "max_attempts":5,"backoff_base_s":1,"backoff_max_s":60,"timeout_s":10}'
```

### Request lifecycle

```
queued ──► running ──► succeeded            (status < 400)
   ▲          │
   │          ├──► failed                   (not retryable: 404, TLS error, blocked target, ...)
   │          │
   └─ retry ◄─┤  retryable failure, attempts left: back to queued with a backoff delay
              │
              └──► dead                     (retryable, but out of attempts: the dead-letter queue)
```

## Design decisions

**The queue lives in Postgres.** Workers claim work with `SELECT ... FOR UPDATE SKIP LOCKED`, followed by a
compare-and-swap `UPDATE`, which also keeps it correct on SQLite. One datastore means a request and its
attempts are always consistent, with nothing extra to run. The trade-off is throughput: this comfortably
handles hundreds of requests per second, and a broker (Redis, SQS) would be the next step beyond that.

**Delivery is at-least-once, and the design says so.** If a worker dies after sending but before recording the
result, the request is claimed again once its lease expires (`TRACELAB_LEASE_SECONDS`, default 60). To make
that safe, every retry of a POST/PUT/PATCH/DELETE carries the same `Idempotency-Key` (the request id), so an API that
honors the header can drop the duplicate. A request that dies on its *last* attempt goes to the DLQ as
`worker_lost` instead of running again.

**Retries are selective.** Timeouts, connection errors, 408, 429 and most 5xx are retried. 4xx, TLS errors and
bad URLs are not, because repeating them cannot help. Delay is `min(cap, base * 2^(n-1))` with equal jitter, and a
server's `Retry-After` is honored (capped at the policy maximum).

**Submission idempotency.** The same `Idempotency-Key` with the same payload returns the original request
(`200`, `Idempotent-Replayed: true`). The same key with a different payload is a `409`. A unique index settles races
between concurrent identical submissions.

**Security for a public demo.** TraceLab makes outbound requests on behalf of callers, which is a classic SSRF
surface. Targets resolving to private, loopback or link-local addresses (including cloud metadata) are rejected
at submission and again at send time, and redirects are never followed. Credential headers (`Authorization`,
`Cookie`, `X-API-Key`, ...) are stored so replays work, but masked in every API response. Known limit: the
send-time check resolves DNS separately from the connection, so a hostile DNS server could in theory
rebind between the two; for hostile multi-tenant use, pin the resolved IP or egress through a proxy.

**Observability.** Logs are one JSON object per line (request id, host, attempt, outcome, latency). Every HTTP
response carries `X-Request-ID`. Percentiles are computed in Python over the attempts in the window, which keeps SQLite
and Postgres identical; at very high volume, move this to pre-aggregated rollups.

## Deploying

### Any Linux VM (recommended, about 5 minutes)

```bash
git clone <your repo> && cd tracelab
cp .env.example .env
# edit .env: strong POSTGRES_PASSWORD, a long random TRACELAB_API_KEY, DOMAIN=tracelab.yourdomain.com, WEB_BIND=127.0.0.1
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Point your domain's DNS at the VM and open ports 80 and 443. Caddy obtains and renews the TLS certificate
automatically. The dashboard asks for the API key on first visit. Then run `python scripts/seed_demo.py`
(with `TRACELAB_URL` and `TRACELAB_API_KEY` set) to populate it.

### Managed platforms (Render, Fly.io, Railway, ...)

Deploy `backend/` as a web service with start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, plus a
second instance running `python -m app.worker` (or set `TRACELAB_EMBEDDED_WORKER=true` to run workers inside
the API process on a single free-tier instance). Set `TRACELAB_DATABASE_URL` to the platform's Postgres URL; plain
`postgres://` URLs are accepted. Deploy `frontend/` as a container with
`BACKEND_URL=https://<your-api-host>`.

The `Publish images` workflow pushes both images to GitHub Container Registry on every push to `main`.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRACELAB_DATABASE_URL` | `sqlite:///./tracelab.db` | Use `postgresql+psycopg://...` in production |
| `TRACELAB_API_KEY` | unset | Require `X-API-Key` on `/api` |
| `TRACELAB_ALLOW_PRIVATE_TARGETS` | `false` | Allow private-network targets (local dev only) |
| `TRACELAB_EMBEDDED_WORKER` | `false` | Run workers inside the API process |
| `TRACELAB_WORKER_CONCURRENCY` | `4` | Threads per worker process |
| `TRACELAB_LEASE_SECONDS` | `60` | How long before a silent worker's request is reclaimed |
| `TRACELAB_CORS_ORIGINS` | empty | Comma-separated origins, if the UI is hosted elsewhere |
| `TRACELAB_LOG_LEVEL` | `INFO` | |

## Project layout

```
backend/app/   api.py (routes) · queue.py (claim, retry, DLQ) · executor.py (send one request)
               classify.py (failure diagnosis) · security.py (SSRF, redaction) · stats.py · worker.py
backend/tests/ unit, API and end-to-end tests
frontend/src/  Overview, RequestsView, RequestDrawer, TraceTimeline, SubmitDialog
scripts/       seed_demo.py
```

## Known limitations and next steps

- Schema is created at startup (`create_all`). Add Alembic migrations before the first schema change.
- One shared API key; add per-user auth and per-user request scoping for multi-tenant use.
- `Retry-After` supports the seconds form only, not HTTP dates.
- No data retention policy yet; add a job to prune old attempts.
