import hmac
import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import Header, HTTPException

from .config import get_settings

SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
# Headers httpx must compute itself; letting callers set them breaks framing.
DROPPED_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


class BlockedTarget(Exception):
    pass


def check_url(url: str, *, allow_private: bool) -> str:
    """Validate a target URL and return its hostname.

    Raises ValueError for malformed URLs and BlockedTarget for private destinations (SSRF guard).
    Names that fail to resolve are let through so the worker reports a proper dns_failure.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("URL must be http:// or https:// and include a host")
    host = parts.hostname
    if allow_private:
        return host
    try:
        addrs = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return host
        addrs = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    for addr in addrs:
        if not addr.is_global:
            raise BlockedTarget(f"{host} resolves to non-public address {addr}")
    return host


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k: ("***" if k.lower() in SENSITIVE_HEADERS else v) for k, v in (headers or {}).items()}


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected and not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
