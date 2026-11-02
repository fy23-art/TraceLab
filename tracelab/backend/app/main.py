import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api import public, router
from .config import get_settings
from .logging_setup import configure_logging
from .worker import start_threads

log = logging.getLogger("tracelab.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    db.init()
    stop = threading.Event()
    if settings.embedded_worker:
        start_threads(settings, stop)
        logging.getLogger("tracelab").info("embedded worker started")
    yield
    stop.set()


app = FastAPI(
    title="TraceLab",
    version="1.0.0",
    description="Submit API requests, replay failures, and see why they failed.",
    lifespan=lifespan,
)

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Idempotent-Replayed"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if request.url.path != "/api/health":
        log.info("http", extra={
            "request_id": request_id, "method": request.method, "path": request.url.path,
            "status": response.status_code, "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        })
    return response


app.include_router(public)
app.include_router(router)
