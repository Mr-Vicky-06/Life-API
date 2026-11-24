"""Database engine factory.

Provides two SQLAlchemy async-compatible engines:
- rw_engine: read-write connection (life user)
- ro_engine: read-only connection (life_ro user)

Sessions are created via get_rw_session / get_ro_session FastAPI dependencies.
RO sessions are enforced read-only at both connection and transaction levels.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str, read_only: bool = False):
    connect_args: dict[str, Any] = {"connect_timeout": 2}
    if read_only:
        connect_args["options"] = "-c default_transaction_read_only=on"
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args=connect_args,
    )


def get_rw_engine():
    settings = get_settings()
    return _make_engine(settings.database_url, read_only=False)


def get_ro_engine():
    settings = get_settings()
    return _make_engine(settings.database_url_ro, read_only=True)


# Module-level singletons (created lazily at first use)
_rw_engine = None
_ro_engine = None


def rw_engine():
    global _rw_engine
    if _rw_engine is None:
        _rw_engine = get_rw_engine()
    return _rw_engine


def ro_engine():
    global _ro_engine
    if _ro_engine is None:
        _ro_engine = get_ro_engine()
    return _ro_engine


def reset_engines() -> None:
    """Reset cached engines (useful for tests when switching database URLs)."""
    global _rw_engine, _ro_engine
    if _rw_engine is not None:
        _rw_engine.dispose()
        _rw_engine = None
    if _ro_engine is not None:
        _ro_engine.dispose()
        _ro_engine = None


RWSession = sessionmaker(bind=None, class_=Session, autocommit=False, autoflush=False)
ROSession = sessionmaker(bind=None, class_=Session, autocommit=False, autoflush=False)


def get_rw_session() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a read-write DB session."""
    session = Session(bind=rw_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_ro_session() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a read-only DB session enforced READ ONLY."""
    session = Session(bind=ro_engine())
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
    finally:
        session.close()


@contextmanager
def ro_session_scope() -> Generator[Session, None, None]:
    """Context manager for standalone read-only DB sessions."""
    session = Session(bind=ro_engine())
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
    finally:
        session.close()


def check_db() -> bool:
    """Return True if the DB is reachable via SELECT 1."""
    try:
        with Session(bind=rw_engine()) as s:
            result = s.execute(text("SELECT 1")).scalar()
            return result == 1
    except Exception:
        return False
