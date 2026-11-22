"""Database engine factory.

Provides two SQLAlchemy async-compatible engines:
- rw_engine: read-write connection (life user)
- ro_engine: read-only connection (life_ro user)

Sessions are created via get_rw_session / get_ro_session FastAPI dependencies.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 2},
    )


def get_rw_engine():
    settings = get_settings()
    return _make_engine(settings.database_url)


def get_ro_engine():
    settings = get_settings()
    return _make_engine(settings.database_url_ro)


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


RWSession = sessionmaker(bind=None, class_=Session, autocommit=False, autoflush=False)
ROSession = sessionmaker(bind=None, class_=Session, autocommit=False, autoflush=False)


def get_rw_session():
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


def get_ro_session():
    """FastAPI dependency — yields a read-only DB session."""
    session = Session(bind=ro_engine())
    try:
        yield session
    finally:
        session.close()


def check_db() -> bool:
    """Return True if the DB is reachable."""
    try:
        with Session(bind=rw_engine()) as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
