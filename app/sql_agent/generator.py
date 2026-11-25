"""Structured Text-to-SQL generator and column-aware one-shot SQL error repair."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.gateway.structured import call_structured
from app.sql_agent.schema_prompt import (
    build_date_context,
    build_static_schema_prefix,
    format_view_columns_for_sql,
)


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
    """Generate structured SQL and brief explanation keeping static schema prefix first."""
    cfg = settings or get_settings()
    sys_prompt = system_prompt or build_static_schema_prefix()
    date_ctx = build_date_context(settings=cfg)
    prompt = f"{date_ctx}\nQuestion: {question.strip()}"
    return call_structured(
        GeneratedSQL,
        prompt,
        system=sys_prompt,
        settings=cfg,
    )


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
