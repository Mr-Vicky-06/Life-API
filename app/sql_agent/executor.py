"""Read-only SQL executor enforcing life_ro role, READ ONLY tx, 5s timeout, JSON-safe rows."""
from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import ro_engine

MAX_RESULT_ROWS = 200
DEFAULT_STATEMENT_TIMEOUT_MS = 5000


@dataclass(slots=True)
class SQLExecutionResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


def _to_json_safe(value: Any) -> Any:
    """Convert Postgres/Python scalars into JSON-serializable primitives."""
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def execute_readonly_sql(
    sql: str,
    *,
    session: Session | None = None,
    timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> SQLExecutionResult:
    """Execute validated SQL inside a READ ONLY transaction with SET LOCAL statement_timeout."""
    timeout_int = max(1, int(timeout_ms))

    if session is not None:
        return _run_in_session(session, sql, timeout_int)

    with Session(bind=ro_engine()) as ro_sess:
        return _run_in_session(ro_sess, sql, timeout_int)


def _run_in_session(session: Session, sql: str, timeout_int: int) -> SQLExecutionResult:
    try:
        if not session.in_transaction():
            session.begin()
        # Ensure local statement timeout is enforced even if session already started
        session.execute(text(f"SET LOCAL statement_timeout = '{timeout_int}ms'"))
        result = session.execute(text(sql))
        columns = list(result.keys())
        fetched = result.fetchmany(MAX_RESULT_ROWS)
        rows = [[_to_json_safe(col_val) for col_val in row] for row in fetched]
        return SQLExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )
    except SQLAlchemyError:
        session.rollback()
        raise
