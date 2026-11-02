import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

log = logging.getLogger("tracelab.db")

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def normalize_url(url: str) -> str:
    """Accept the postgres:// style URLs that most hosting platforms hand out."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def init(url: str | None = None, *, wait_seconds: int = 30) -> Engine:
    """(Re)create the engine and make sure the schema exists. Safe to call from many processes."""
    global _engine, _sessionmaker
    url = normalize_url(url or get_settings().database_url)
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)

    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with engine.begin() as conn:
                if engine.dialect.name == "postgresql":
                    # Serialize schema creation when the API and workers boot together.
                    conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
                Base.metadata.create_all(conn)
            break
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            log.warning("database not ready, retrying")
            time.sleep(1)

    if _engine is not None:
        _engine.dispose()
    _engine, _sessionmaker = engine, sessionmaker(engine, expire_on_commit=False)
    return engine


def new_session() -> Session:
    if _sessionmaker is None:
        init()
    assert _sessionmaker is not None
    return _sessionmaker()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
