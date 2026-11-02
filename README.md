# TraceLab


## Contents

1. [Introduction](#introduction)
2. [Motivation](#motivation)
3. [Who it is for](#who-it-is-for)
4. [Tech stack](#tech-stack)
5. [How it works](#how-it-works)
6. [Deployment guide for beginners](#deployment-guide-for-beginners)
7. [Using TraceLab](#using-tracelab)
8. [Configuration reference](#configuration-reference)
9. [Development and testing](#development-and-testing)
10. [Design decisions and limitations](#design-decisions-and-limitations)

---

## Introduction

TraceLab does four things:

- **Delivers requests reliably.** Submit a request (method, URL, headers, body, timeout, retry policy). A background
  worker sends it, retries transient failures with exponential backoff and jitter, and honors a server's `Retry-After`.
- **Explains failures.** Every failed attempt is classified (DNS failure, connection refused, timeout, TLS error,
  rate limit, 5xx, and so on) and shown with a plain-English explanation and a suggested fix.
- **Lets you replay.** Replay any request as a new one linked to the original, or give a dead-lettered request more
  attempts.
- **Shows the numbers.** A React dashboard displays success rate, p50/p95/p99 latency, per-host health, queue depth,
  and a waterfall of every attempt with the backoff waits between them.

## Motivation

Calling other people's APIs is where most production surprises come from. Payment providers time out, webhooks hit a
server mid-deploy, and a rate limit appears only under load. When that happens, developers usually end up asking the
same questions:

- *Did the request actually go out, and how many times?*
- *Was it my bug, their outage, or the network?*
- *Is it safe to send it again?*

Most teams answer these with log searches and one-off scripts. TraceLab turns that into a product: failures are
retried automatically, every attempt is recorded, the cause is stated in plain language, and replaying is a button
rather than a rewritten `curl` command.

It is also a compact, complete example of the patterns behind reliable backend systems: a durable job queue,
at-least-once delivery, idempotency keys, backoff with jitter, dead-letter queues, crash recovery with leases, and
defense against server-side request forgery (SSRF).

## Who it is for

| If you are... | TraceLab helps you... |
| --- | --- |
| A backend developer integrating third-party APIs (payments, email, CRMs) | Stop writing ad-hoc retry loops and see exactly what happened to each call |
| A small team that sends webhooks or background HTTP calls | Get retries, a dead-letter queue and replay without running a message broker |
| An on-call engineer or SRE | Tell "their outage" from "our bug" quickly, using latency and error-rate charts per host |
| A student or engineer learning reliability patterns | Read a small, tested codebase that implements queues, retries and idempotency end to end |

TraceLab is not a replacement for a full API gateway or a large-scale message broker. It is built for hundreds of
requests per second on a single Postgres database, not millions.

## Tech stack

| Layer | Technology | Why |
| --- | --- | --- |
| API | Python 3.12, FastAPI, Pydantic | Typed request validation and automatic OpenAPI docs |
| Database access | SQLAlchemy 2, psycopg 3 | Same code runs on PostgreSQL (production) and SQLite (tests and quick local runs) |
| Job queue | PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`) | One datastore means a request and its attempts are always consistent |
| Outbound HTTP | httpx | Fine-grained timeouts and streaming reads with a size cap |
| Worker | Python threads, run as a separate process | Scales by adding worker containers |
| Dashboard | React 18, TypeScript, Vite, Recharts | Fast build, type-checked UI, self-hosted IBM Plex fonts |
| Web server | nginx | Serves the dashboard and proxies `/api` to the backend |
| Packaging | Docker, Docker Compose | One command starts everything |
| HTTPS | Caddy (optional overlay) | Automatic TLS certificates |
| Quality | pytest (70 tests), Ruff, TypeScript strict mode, GitHub Actions | CI runs the suite on SQLite and PostgreSQL |

## How it works

```
 browser ──► nginx (web) ──► FastAPI (api) ──► PostgreSQL ◄── worker(s)
              static React        │          requests + attempts      │
                                  └─ validates, stores, serves stats  └─ claims due requests, sends them,
                                                                          records every attempt
```

A request moves through these states:

```
queued ──► running ──► succeeded            (status below 400)
   ▲          │
   │          ├──► failed                   (not retryable: 404, TLS error, blocked target)
   │          │
   └─ retry ◄─┤  retryable failure with attempts left: back to queued after a backoff delay
              │
              └──► dead                     (retryable, but out of attempts: the dead-letter queue)
```

---

## Deployment guide for beginners

This guide assumes you have never run this project. It has two parts: **A. run it on your own computer** (10
minutes, no cost) and **B. put it on the internet** (about 30 minutes, a small monthly server fee).

### Before you start: what you need

| Need | For | How to get it |
| --- | --- | --- |
| Git | Downloading the code | https://git-scm.com/downloads |
| Docker | Running everything in containers | Docker Desktop (Windows, Mac) from https://www.docker.com/products/docker-desktop, or Docker Engine on Linux |
| A GitHub account | Hosting your copy of the code (optional but recommended) | https://github.com |
| A server and a domain name | Part B only | See Part B |

To check that Docker works, open a terminal (PowerShell on Windows, Terminal on Mac or Linux) and run:

```bash
docker --version
docker compose version
```

Both commands should print a version number.

### Part A: run it on your computer

**Step 1. Get the code.**

```bash
git clone https://github.com/<your-username>/tracelab.git
cd tracelab
```

(If you downloaded a zip instead, unzip it and `cd` into the `tracelab` folder.)

**Step 2. Create your settings file.**

```bash
cp .env.example .env
```

On Windows PowerShell use `copy .env.example .env`. The defaults work for local use. You can leave
`TRACELAB_API_KEY` empty for now.

**Step 3. Start everything.**

```bash
docker compose up -d --build
```

The first run downloads images and builds the app, which takes a few minutes. This starts four containers:
`db` (PostgreSQL), `api` (the backend), `worker` (sends your requests) and `web` (the dashboard).

**Step 4. Check that it is running.**

```bash
docker compose ps
```

All four services should show `running` (the `api` service should also say `healthy`).

**Step 5. Open the dashboard.** Go to http://localhost:8080 in your browser. The interactive API documentation is
at http://localhost:8000/docs.

**Step 6. Send your first request.** Click **Send a request**, choose the **Server error, retried** example, and
click **Send request**. Watch the attempt timeline fill in as TraceLab retries with growing delays, then check the
**Dead letters** tab.

**Step 7 (optional). Add demo data.** This queues about 60 realistic requests so the charts have something to show.
It needs the internet (it uses httpbin.org as a test target) and Python 3:

```bash
python scripts/seed_demo.py
```

**Useful commands:**

```bash
docker compose logs -f worker     # watch requests being sent (JSON logs)
docker compose down               # stop everything, keep your data
docker compose down -v            # stop everything and delete all data
```

> By default TraceLab refuses to send requests to private network addresses such as `localhost` or `10.x.x.x`.
> This protects you from server-side request forgery. If you want to test against a service on your own machine,
> set `TRACELAB_ALLOW_PRIVATE_TARGETS=true` in `.env`, run `docker compose up -d`, and **never** enable it on a
> public server.

### Part B: put it on the internet

You will rent a small Linux server, point a domain name at it, and let Caddy handle HTTPS automatically.

**Step 1. Rent a server.** Any provider works (DigitalOcean, Hetzner, AWS Lightsail, Vultr, ...). Choose
**Ubuntu 24.04**, at least **2 GB of RAM**, and add your SSH key or note the root password. Write down the
server's public IP address.

**Step 2. Buy or choose a domain and point it at the server.** In your domain provider's DNS settings, create an
**A record**: name `tracelab` (or `@`), value = your server's IP address. DNS can take a few minutes to update.
You can check with `ping tracelab.yourdomain.com`.

**Step 3. Connect to the server and install Docker.**

```bash
ssh root@<your-server-ip>
curl -fsSL https://get.docker.com | sh
```

**Step 4. Open only the ports you need.** On Ubuntu:

```bash
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

(Some providers also have a separate cloud firewall in their web console; allow ports 22, 80 and 443 there too.)

**Step 5. Get the code onto the server.**

```bash
git clone https://github.com/<your-username>/tracelab.git
cd tracelab
cp .env.example .env
```

**Step 6. Fill in your settings.** Generate two strong secrets:

```bash
openssl rand -hex 24    # use the output as POSTGRES_PASSWORD
openssl rand -hex 32    # use the output as TRACELAB_API_KEY
```

Then edit `.env` with `nano .env`:

```
POSTGRES_PASSWORD=<first secret>
TRACELAB_API_KEY=<second secret>
TRACELAB_ALLOW_PRIVATE_TARGETS=false
DOMAIN=tracelab.yourdomain.com
WEB_BIND=127.0.0.1
```

Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`. Keep the API key somewhere safe, such as a password manager:
it is the password for your dashboard.

**Step 7. Start TraceLab with HTTPS.**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Caddy requests a free TLS certificate for your domain the first time. This works only if DNS from Step 2 has
updated and ports 80 and 443 are open.

**Step 8. Verify.**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl https://tracelab.yourdomain.com/api/health
```

The second command should print `{"status":"ok"}`. Open `https://tracelab.yourdomain.com` in your browser, paste your
API key when asked, and you are in.

**Step 9 (optional). Add demo data** from your own computer:

```bash
TRACELAB_URL=https://tracelab.yourdomain.com TRACELAB_API_KEY=<your key> python scripts/seed_demo.py
```

#### Operating it

```bash
cd tracelab
alias tl='docker compose -f docker-compose.yml -f docker-compose.prod.yml'

tl logs -f worker api            # watch logs
git pull && tl up -d --build     # update to the latest code
tl restart worker                # restart one service
docker compose exec db pg_dump -U tracelab tracelab > backup-$(date +%F).sql   # back up the database
```

#### If something goes wrong

| Symptom | Likely cause and fix |
| --- | --- |
| Browser shows a certificate error or no page | DNS has not updated yet, or ports 80/443 are blocked. Check with `tl logs caddy`. |
| Dashboard asks for the key again and rejects it | The key in `.env` differs from what you typed. After editing `.env`, run `tl up -d`. |
| `api` never becomes healthy | Check `tl logs api`. A wrong `POSTGRES_PASSWORD` after the first start is the usual cause: the database keeps the first password. Fix with `tl down -v` (this deletes data) and start again. |
| Requests stay "queued" forever | The worker is not running. Check `tl ps` and `tl logs worker`. |
| A request fails with "blocked target" | You pointed it at a private address. This is intentional protection. |

#### Other hosting options

- **Render, Fly.io, Railway:** deploy `backend/` as a web service with start command
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, plus a second service running `python -m app.worker` (or set
  `TRACELAB_EMBEDDED_WORKER=true` to run the worker inside the API on a single small instance). Set
  `TRACELAB_DATABASE_URL` to the platform's Postgres URL (plain `postgres://` URLs are accepted). Deploy `frontend/`
  as a container with `BACKEND_URL=https://<your-api-host>`.
- **Prebuilt images:** the included GitHub Action publishes both images to GitHub Container Registry on every push
  to `main`.

---

## Using TraceLab

### From the dashboard

- **Overview:** success rate, latency percentiles, queue depth, charts, failure causes and per-host health.
- **Requests:** every request, filterable by state and searchable by URL. Click one to see its attempt timeline,
  the reason it failed, and response previews.
- **Dead letters:** requests that ran out of attempts. Open one and choose **Retry 3 more times** or **Replay request**.

### From the API

All routes live under `/api`. If an API key is configured, send it as the `X-API-Key` header.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/requests` | Queue an outbound request (returns `202`). Honors an `Idempotency-Key` header. |
| `GET` | `/requests` | List requests. Filters: `status`, `host`, `q`, `limit`, `offset`. |
| `GET` | `/requests/{id}` | Full detail with every attempt and the failure diagnosis. |
| `POST` | `/requests/{id}/replay` | Send the same request again as a new, linked request. |
| `GET` | `/dlq` | List dead-lettered requests. |
| `POST` | `/dlq/{id}/requeue` | Give a dead request more attempts. |
| `GET` | `/stats` | Rates, percentiles, time series, failure causes, hosts, queue depth. |
| `GET` | `/health` | Liveness and database check. |

Example:

```bash
curl -X POST https://tracelab.yourdomain.com/api/requests \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <your key>' \
  -H 'Idempotency-Key: order-1042' \
  -d '{"method":"POST","url":"https://api.example.com/orders",
       "headers":{"Content-Type":"application/json"},"body":"{\"id\":1042}",
       "max_attempts":5,"backoff_base_s":1,"backoff_max_s":60,"timeout_s":10}'
```

Submitting the same `Idempotency-Key` with the same payload returns the original request instead of creating a
duplicate. The same key with a different payload returns `409`.

## Configuration reference

All settings are environment variables, set through `.env` when using Docker Compose.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `change-me` | Database password (Compose only). Always change it. |
| `TRACELAB_API_KEY` | empty | When set, `/api` requires `X-API-Key`. Always set it on a public server. |
| `TRACELAB_ALLOW_PRIVATE_TARGETS` | `false` | Allow targets on private networks. Local development only. |
| `TRACELAB_DATABASE_URL` | SQLite file | `postgresql+psycopg://...` in production (set automatically by Compose). |
| `TRACELAB_EMBEDDED_WORKER` | `false` | Run workers inside the API process. |
| `TRACELAB_WORKER_CONCURRENCY` | `4` | Worker threads per worker process. |
| `TRACELAB_LEASE_SECONDS` | `60` | Time before a silent worker's request is picked up again. |
| `TRACELAB_CORS_ORIGINS` | empty | Comma-separated origins if the dashboard is hosted on another domain. |
| `TRACELAB_LOG_LEVEL` | `INFO` | Log verbosity. |
| `DOMAIN` | none | Domain for automatic HTTPS (production overlay). |
| `WEB_PORT` / `WEB_BIND` | `8080` / `0.0.0.0` | Dashboard port and bind address. |

## Development and testing

```bash
# Backend (Python 3.12). Uses SQLite by default, so no database setup is needed.
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload            # API on :8000 (add TRACELAB_EMBEDDED_WORKER=true to also run a worker)
python -m app.worker                     # worker, in a second terminal

# Frontend
cd frontend
npm install
npm run dev                              # http://localhost:5173, proxies /api to :8000
```

Run the checks:

```bash
cd backend && ruff check . && python -m pytest -q
TRACELAB_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/test python -m pytest -q   # on Postgres
cd frontend && npm run build             # type-check and bundle
```

The tests cover failure classification, the SSRF guard, queue behavior (backoff bounds, leases, dead letters,
eight threads claiming work at once), the whole HTTP API, and end-to-end runs against a local server that fails on
purpose.

```
backend/app/    api.py (routes) · queue.py (claim, retry, dead letters) · executor.py (send one request)
                classify.py (failure diagnosis) · security.py (SSRF guard, redaction) · stats.py · worker.py
backend/tests/  unit, API and end-to-end tests
frontend/src/   Overview · RequestsView · RequestDrawer · TraceTimeline · SubmitDialog
scripts/        seed_demo.py
```

## Design decisions and limitations

- **At-least-once delivery.** If a worker dies after sending a request but before recording the result, the request
  is sent again after its lease expires. To make this safe, every retry of a POST, PUT, PATCH or DELETE carries the
  same `Idempotency-Key` header (the TraceLab request id), so an API that honors it can ignore the duplicate.
- **Selective retries.** Timeouts, connection errors, 408, 429 and most 5xx responses are retried. Other 4xx
  responses, TLS errors and malformed URLs are not, because repeating them cannot help.
- **SSRF protection.** Targets that resolve to private, loopback or link-local addresses (including cloud metadata
  endpoints) are rejected at submission and again at send time. Redirects are never followed. Credential headers are
  stored so replays work but are masked in every API response.
- **Known limits.** The database schema is created at startup, so add migrations (Alembic) before changing it. There
  is a single shared API key rather than per-user accounts. `Retry-After` supports the seconds form only. There is no
  data-retention job yet. The send-time DNS check is separate from the connection, so for hostile multi-tenant use,
  pin the resolved IP or route traffic through an egress proxy.
