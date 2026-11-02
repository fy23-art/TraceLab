"""Sends one HTTP request and turns whatever happens into an AttemptResult. Never raises."""

import time
from dataclasses import dataclass

import httpx

from .classify import REGISTRY, classify_exception, classify_status
from .config import Settings
from .models import utcnow
from .queue import AttemptResult
from .security import BlockedTarget, check_url

MAX_READ_BYTES = 1024 * 1024  # stop reading huge responses; we only keep a small preview anyway


@dataclass
class RequestSnapshot:
    """Plain copy of the fields needed to send a request, so no DB session is held during I/O."""

    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    timeout_s: float


UNSAFE_METHODS = {"POST", "PATCH", "DELETE", "PUT"}


def outbound_headers(method: str, headers: dict[str, str], request_id: str, attempt: int) -> dict[str, str]:
    """Headers actually sent upstream.

    Every retry of the same request carries the same Idempotency-Key (the TraceLab request id), so an
    API that honors the header can ignore a duplicate when a retry follows an ambiguous failure such as
    a timeout after the server already did the work. A key the caller set explicitly always wins.
    """
    out = dict(headers)
    names = {k.lower() for k in out}
    if method in UNSAFE_METHODS and "idempotency-key" not in names:
        out["Idempotency-Key"] = request_id
    out.setdefault("X-TraceLab-Attempt", str(attempt))
    out.setdefault("X-TraceLab-Request-Id", request_id)
    return out


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None  # HTTP-date form is rare; fall back to our own backoff


def execute(snap: RequestSnapshot, settings: Settings, transport: httpx.BaseTransport | None = None) -> AttemptResult:
    started = utcnow()
    t0 = time.perf_counter()

    def finish(**kw) -> AttemptResult:
        return AttemptResult(started_at=started, finished_at=utcnow(),
                             latency_ms=(time.perf_counter() - t0) * 1000, **kw)

    try:
        check_url(snap.url, allow_private=settings.allow_private_targets)
        # Redirects are not followed: a public URL must not be able to bounce us to a private one.
        with httpx.Client(transport=transport, follow_redirects=False, trust_env=False,
                          timeout=httpx.Timeout(snap.timeout_s)) as client:
            with client.stream(snap.method, snap.url, headers=snap.headers,
                               content=snap.body.encode() if snap.body is not None else None) as resp:
                preview, total = bytearray(), 0
                cap = settings.response_capture_bytes
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if len(preview) < cap:
                        preview.extend(chunk[: cap - len(preview)])
                    if total >= MAX_READ_BYTES:
                        break
                    if time.perf_counter() - t0 > snap.timeout_s:
                        raise httpx.ReadTimeout("overall deadline exceeded while reading the body")
                headers = {k.lower(): v for k, v in resp.headers.items()}
                text = preview.decode("utf-8", "replace") + ("\n[truncated]" if total > cap else "")
                diagnosis = classify_status(resp.status_code)
                common = dict(status_code=resp.status_code, response_headers=headers,
                              response_body=text, response_bytes=total)
                if diagnosis is None:
                    return finish(success=True, **common)
                return finish(
                    success=False, error_kind=diagnosis.kind, retryable=diagnosis.retryable,
                    error_message=f"HTTP {resp.status_code} {resp.reason_phrase}",
                    retry_after_s=_parse_retry_after(headers.get("retry-after")), **common,
                )
    except BlockedTarget as exc:
        return finish(success=False, error_kind="blocked_target", retryable=False, error_message=str(exc))
    except ValueError as exc:
        return finish(success=False, error_kind="invalid_url", retryable=False, error_message=str(exc))
    except Exception as exc:  # noqa: BLE001 - every failure must become a recorded attempt
        diagnosis = classify_exception(exc) if isinstance(exc, httpx.HTTPError | OSError) else REGISTRY["unexpected"]
        return finish(success=False, error_kind=diagnosis.kind, retryable=diagnosis.retryable,
                      error_message=f"{type(exc).__name__}: {exc}")
