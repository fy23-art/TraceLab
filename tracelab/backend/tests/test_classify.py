import socket

import httpx
import pytest

from app.classify import classify_exception, classify_status


@pytest.mark.parametrize(
    "code,kind,retryable",
    [
        (500, "server_error", True), (502, "bad_gateway", True), (503, "unavailable", True),
        (429, "rate_limited", True), (408, "request_timeout", True), (404, "not_found", False),
        (401, "auth_error", False), (403, "auth_error", False), (422, "client_error", False),
        (501, "not_implemented", False),
    ],
)
def test_status_classification(code, kind, retryable):
    d = classify_status(code)
    assert (d.kind, d.retryable) == (kind, retryable)


@pytest.mark.parametrize("code", [200, 201, 204, 301, 304])
def test_success_statuses_have_no_diagnosis(code):
    assert classify_status(code) is None


def test_dns_failure_found_through_cause_chain():
    exc = httpx.ConnectError("boom")
    exc.__cause__ = socket.gaierror(-2, "Name or service not known")
    assert classify_exception(exc).kind == "dns_failure"


def test_connection_refused():
    exc = httpx.ConnectError("boom")
    exc.__cause__ = ConnectionRefusedError()
    assert classify_exception(exc).kind == "connection_refused"


def test_timeouts():
    assert classify_exception(httpx.ConnectTimeout("x")).kind == "connect_timeout"
    assert classify_exception(httpx.ReadTimeout("x")).kind == "read_timeout"
    assert classify_exception(httpx.PoolTimeout("x")).kind == "timeout"


def test_unknown_exception():
    d = classify_exception(RuntimeError("?"))
    assert d.kind == "unexpected" and not d.retryable
