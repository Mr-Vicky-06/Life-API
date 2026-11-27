"""Structured Text-to-SQL generator and column-aware one-shot SQL error repair."""
from __future__ import annotations

import logging
import re

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp

from app.config import Settings, get_settings
from app.gateway.structured import call_structured
from app.sql_agent.schema_prompt import (
    build_date_context,
    build_static_schema_prefix,
    format_view_columns_for_sql,
)

logger = logging.getLogger(__name__)

_TIME_WINDOW_RE = re.compile(
    r"\b("
    r"last|past|previous|prior|recent|between|since|before|after|until|during|"
    r"today|yesterday|tonight|this\s+(week|month|year)|"
    r"in\s+(january|february|march|april|may|june|july|august|september|october|november|"
    r"december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)|"
    r"20\d{2}"
    r")\b|\b\d{4}-\d{2}(?:-\d{2})?\b",
    re.IGNORECASE,
)
_DATE_COLUMN_NAMES = frozenset({"date", "commit_date", "committed_at"})
_RANGE_CMP_NODES = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)


def has_time_window_expression(question: str) -> bool:
    """Return True when question explicitly specifies a time window, date range, or date."""
    return bool(_TIME_WINDOW_RE.search(question))


def has_spurious_date_window(sql: str, question: str) -> bool:
    """Detect a date/range WHERE predicate emitted despite no time-window wording in question."""
    if has_time_window_expression(question):
        return False
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return False
    for where in tree.find_all(exp.Where):
        for cmp_node in where.find_all(_RANGE_CMP_NODES):
            if isinstance(getattr(cmp_node, "this", None), exp.Extract):
                continue
            cols = {c.name.lower() for c in cmp_node.find_all(exp.Column)}
            if cols & _DATE_COLUMN_NAMES:
                return True
            if any(
                cmp_node.find(node_type) is not None
                for node_type in (exp.Date, exp.Interval, exp.CurrentDate, exp.CurrentTimestamp)
            ):
                return True
    return False


class GeneratedSQL(BaseModel):
    sql: str = Field(min_length=1, description="Single PostgreSQL SELECT query.")
    explanation: str = Field(
        min_length=1,
        description="One short sentence (max 15 words) explaining what the SQL computes.",
    )


def generate_sql(
    question: str,
    *,
    settings: Settings | None = None,
    system_prompt: str | None = None,
) -> GeneratedSQL:
    """Generate structured SQL and regenerate once if an unrequested date filter is emitted."""
    cfg = settings or get_settings()
    sys_prompt = system_prompt or build_static_schema_prefix()
    date_ctx = build_date_context(settings=cfg)
    prompt = f"{date_ctx}\nQuestion: {question.strip()}"
    result = call_structured(
        GeneratedSQL,
        prompt,
        system=sys_prompt,
        settings=cfg,
    )
    if has_spurious_date_window(result.sql, question):
        logger.info("Detected unrequested date WHERE filter; regenerating once.")
        retry_prompt = (
            f"{prompt}\n\n"
            "Constraint check: Your previous SQL added a date range WHERE filter, but the "
            "question asks across ALL available data with NO time window (words like 'weekly' "
            "or 'monthly' mean GROUP BY truncation only). Regenerate without any date WHERE filter."
        )
        return call_structured(
            GeneratedSQL,
            retry_prompt,
            system=sys_prompt,
            settings=cfg,
        )
    return result


def repair_sql(
    question: str,
    failed_sql: str,
    error_text: str,
    *,
    settings: Settings | None = None,
    system_prompt: str | None = None,
) -> GeneratedSQL:
    """Attempt one LLM repair of a SQL query with exact referenced-view columns & DB error."""
    cfg = settings or get_settings()
    sys_prompt = system_prompt or build_static_schema_prefix()
    date_ctx = build_date_context(settings=cfg)
    view_columns_hint = format_view_columns_for_sql(failed_sql)
    prompt = (
        f"{date_ctx}\n"
        f"Question: {question.strip()}\n\n"
        f"Previous SQL query failed during PostgreSQL execution:\n{failed_sql}\n\n"
        f"Database error:\n{error_text[:600]}\n\n"
        f"{view_columns_hint}\n\n"
        "Fix the SQL query using ONLY the exact column names listed above and return valid JSON."
    )
    return call_structured(
        GeneratedSQL,
        prompt,
        system=sys_prompt,
        settings=cfg,
    )
