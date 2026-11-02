"""Turns raw failures (HTTP statuses and transport exceptions) into a diagnosis a human can act on."""

import socket
import ssl
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Diagnosis:
    kind: str
    retryable: bool
    explanation: str
    suggestion: str


def _d(kind: str, retryable: bool, explanation: str, suggestion: str) -> Diagnosis:
    return Diagnosis(kind, retryable, explanation, suggestion)


REGISTRY: dict[str, Diagnosis] = {
    d.kind: d
    for d in [
        _d("dns_failure", True, "The hostname could not be resolved to an IP address.",
           "Check the hostname for typos. If it is correct, the DNS record may be missing or DNS is having a transient outage."),
        _d("connection_refused", True, "The host was reachable but nothing is listening on that port.",
           "Confirm the service is running and the port is right. A deploy or restart in progress also looks like this."),
        _d("connect_timeout", True, "No connection could be established before the timeout.",
           "The host may be down, overloaded, or filtered by a firewall. Try a longer timeout or check network rules."),
        _d("read_timeout", True, "The connection was made but the server did not answer in time.",
           "The endpoint is slow. Raise the timeout if the work is legitimately long, or look for slow queries upstream."),
        _d("timeout", True, "The request timed out.", "Raise the timeout or check the upstream service's latency."),
        _d("connection_reset", True, "The server closed the connection before sending a full response.",
           "Usually a crashed or restarting process, or a proxy dropping the connection. Check the server's logs."),
        _d("tls_error", False, "The TLS handshake failed or the certificate was rejected.",
           "Check that the certificate is valid, not expired, and matches the hostname."),
        _d("invalid_url", False, "The URL could not be parsed or has an unsupported scheme.",
           "Use a full http:// or https:// URL."),
        _d("blocked_target", False, "The target resolves to a private, loopback or link-local address, which is blocked.",
           "Point the request at a public host. Operators can lift this with TRACELAB_ALLOW_PRIVATE_TARGETS=true."),
        _d("worker_lost", False, "A worker claimed this request and never reported back.",
           "The worker likely crashed mid-request. Replay it if the call is safe to repeat."),
        _d("unexpected", False, "An unexpected error happened while sending the request.",
           "Check the worker logs for the stack trace."),
        _d("rate_limited", True, "The server is rate limiting this client (HTTP 429).",
           "Slow down. TraceLab honors Retry-After when the server sends it."),
        _d("request_timeout", True, "The server gave up waiting for the request (HTTP 408).", "Retrying usually works."),
        _d("auth_error", False, "The server rejected the credentials (HTTP 401/403).",
           "Check the Authorization header or API key and its permissions."),
        _d("not_found", False, "The server has no resource at this URL (HTTP 404).", "Check the path and any IDs in it."),
        _d("client_error", False, "The server rejected the request as invalid (HTTP 4xx).",
           "Fix the request. Retrying the same request will not help."),
        _d("bad_gateway", True, "A gateway or proxy got a bad answer from the upstream service (HTTP 502/504).",
           "The upstream service is probably restarting or overloaded."),
        _d("unavailable", True, "The service says it is temporarily unavailable (HTTP 503).",
           "Usually maintenance or overload. TraceLab will back off and retry."),
        _d("server_error", True, "The server hit an internal error (HTTP 5xx).",
           "The bug is on the server side. Check its logs for the failing request."),
        _d("not_implemented", False, "The server does not support this request (HTTP 501/505).",
           "Use a different method or protocol version."),
    ]
}


def diagnosis_for_kind(kind: str | None) -> Diagnosis | None:
    return REGISTRY.get(kind) if kind else None


def classify_status(code: int) -> Diagnosis | None:
    """None means the status counts as a success (anything below 400)."""
    if code < 400:
        return None
    by_code = {
        408: "request_timeout", 429: "rate_limited", 401: "auth_error", 403: "auth_error",
        404: "not_found", 502: "bad_gateway", 504: "bad_gateway", 503: "unavailable",
        501: "not_implemented", 505: "not_implemented",
    }
    if code in by_code:
        return REGISTRY[by_code[code]]
    return REGISTRY["client_error"] if code < 500 else REGISTRY["server_error"]


def _causes(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def classify_exception(exc: BaseException) -> Diagnosis:
    chain = list(_causes(exc))
    if any(isinstance(e, socket.gaierror) for e in chain):
        return REGISTRY["dns_failure"]
    if any(isinstance(e, ssl.SSLError) for e in chain):
        return REGISTRY["tls_error"]
    if any(isinstance(e, ConnectionRefusedError) for e in chain):
        return REGISTRY["connection_refused"]
    if any(isinstance(e, ConnectionResetError | BrokenPipeError) for e in chain):
        return REGISTRY["connection_reset"]
    if isinstance(exc, httpx.ConnectTimeout):
        return REGISTRY["connect_timeout"]
    if isinstance(exc, httpx.ReadTimeout):
        return REGISTRY["read_timeout"]
    if isinstance(exc, httpx.TimeoutException):
        return REGISTRY["timeout"]
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol):
        return REGISTRY["invalid_url"]
    if isinstance(exc, httpx.ConnectError):
        return REGISTRY["connect_timeout"] if "timed out" in str(exc).lower() else REGISTRY["connection_refused"]
    if isinstance(exc, httpx.RemoteProtocolError | httpx.ReadError | httpx.WriteError):
        return REGISTRY["connection_reset"]
    return REGISTRY["unexpected"]
