import os

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.models import Base


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """Fresh database per test (SQLite by default, Postgres if TRACELAB_TEST_DATABASE_URL is set).

    Private targets are allowed so tests can hit 127.0.0.1.
    """
    url = os.environ.get("TRACELAB_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("TRACELAB_DATABASE_URL", url)
    monkeypatch.setenv("TRACELAB_ALLOW_PRIVATE_TARGETS", "true")
    monkeypatch.delenv("TRACELAB_API_KEY", raising=False)
    get_settings.cache_clear()
    engine = db.init()
    if engine.dialect.name != "sqlite":
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    yield
    get_settings.cache_clear()


@pytest.fixture
def session():
    s = db.new_session()
    yield s
    s.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
