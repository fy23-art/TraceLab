import pytest

from app.security import BlockedTarget, check_url, redact_headers


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:8000/", "http://10.0.0.5/x", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
])
def test_private_targets_blocked(url):
    with pytest.raises(BlockedTarget):
        check_url(url, allow_private=False)


def test_private_allowed_when_enabled():
    assert check_url("http://127.0.0.1:9000/", allow_private=True) == "127.0.0.1"


def test_public_ip_allowed():
    assert check_url("https://93.184.216.34/", allow_private=False) == "93.184.216.34"


@pytest.mark.parametrize("url", ["ftp://example.com", "file:///etc/passwd", "http://", "not a url"])
def test_bad_urls(url):
    with pytest.raises(ValueError):
        check_url(url, allow_private=False)


def test_redaction():
    out = redact_headers({"Authorization": "Bearer abc", "X-Api-Key": "k", "Accept": "json"})
    assert out == {"Authorization": "***", "X-Api-Key": "***", "Accept": "json"}
