"""
api/services/db.py — SQLAlchemy 2.0 engine + session factory.

One engine per process, with pool sizing / pre-ping / a server-side statement
timeout all driven by env (see api.settings). The same helpers are imported by
the Celery worker so both processes share connection discipline.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from api.settings import get_api_settings
from pipeline.storage import normalize_db_url

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        s = get_api_settings()
        url = normalize_db_url(s.database_url)
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = create_engine(
            url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,
            future=True,
            # server-side guard so a runaway query can't pin a connection forever
            connect_args={"options": f"-c statement_timeout={s.db_statement_timeout_ms}"},
        )
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _Session is None:
        get_engine()
    assert _Session is not None
    return _Session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context (commit on success, rollback on error)."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
