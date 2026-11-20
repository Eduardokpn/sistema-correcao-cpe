"""Engine and session management for the data package.

The connection string comes from the CPE_DATABASE_URL environment variable and
defaults to a local SQLite file next to the back/ package. Because everything
goes through SQLAlchemy, moving to PostgreSQL is just a matter of pointing that
variable at a postgresql:// URL - no code change here or in the models.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base

DATABASE_URL_ENV = "CPE_DATABASE_URL"
# Stored at back/cpe_omr.db by default
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "cpe_omr.db"

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def database_url() -> str:
    """Resolve the connection string from the environment or the SQLite default."""
    configured = os.environ.get(DATABASE_URL_ENV)
    if configured:
        return configured
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine(url: Optional[str] = None, echo: bool = False) -> Engine:
    """Return the process-wide engine, creating it on first use.

    Passing an explicit url (e.g. an in-memory SQLite URL in tests) builds a
    fresh engine without touching the cached default one.
    """
    global _engine, _SessionFactory

    if url is not None:
        engine = _build_engine(url, echo=echo)
        return engine

    if _engine is None:
        _engine = _build_engine(database_url(), echo=echo)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _build_engine(url: str, echo: bool = False) -> Engine:
    connect_args = {}
    engine_kwargs = {}
    if _is_sqlite(url):
        # Allow use across threads (Streamlit / FastAPI workers) for SQLite
        connect_args["check_same_thread"] = False
        if ":memory:" in url or url == "sqlite://":
            # A private in-memory DB lives only as long as its connection; share
            # one connection across sessions so the schema created up front
            # stays visible to every session (used by tests).
            engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(
        url,
        echo=echo,
        future=True,
        connect_args=connect_args,
        **engine_kwargs,
    )

    if _is_sqlite(url):
        # SQLite ignores foreign keys unless asked; turn them on so the
        # ON DELETE rules in the models actually apply.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory() -> sessionmaker:
    """Return the session factory bound to the default engine."""
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    return _SessionFactory


def get_session() -> Session:
    """Create a new Session bound to the default engine."""
    return get_session_factory()()


@contextmanager
def session_scope(session: Optional[Session] = None) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error.

    Accepts an existing session (used unchanged, caller owns its lifecycle) or
    opens and closes its own when none is given.
    """
    if session is not None:
        yield session
        return

    new_session = get_session()
    try:
        yield new_session
        new_session.commit()
    except Exception:
        new_session.rollback()
        raise
    finally:
        new_session.close()


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all tables. Convenience for tests and first-run bootstrapping.

    Production schema changes should go through Alembic migrations; this mirrors
    the same metadata so an empty database can be stood up directly.
    """
    Base.metadata.create_all(engine or get_engine())


def reset_engine() -> None:
    """Drop the cached engine/session factory. Mainly for tests."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
