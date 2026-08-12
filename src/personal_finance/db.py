"""SQLAlchemy engine and session factories."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from .config import database_url


def create_database_engine(url: str | None = None) -> Engine:
    """Create a synchronous engine suitable for local SQLite and future SQL databases."""
    resolved_url = url or database_url()
    parsed = make_url(resolved_url)
    if parsed.drivername.startswith("sqlite") and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(resolved_url, future=True)


def create_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Return a configured session factory."""
    return sessionmaker(bind=create_database_engine(url), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield one transactional session, rolling back failures."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
