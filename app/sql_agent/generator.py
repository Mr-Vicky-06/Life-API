"""Structured Text-to-SQL generator and one-shot SQL error repair."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.gateway.structured import call_structured
from app.sql_agent.schema_prompt import build_schema_prompt


class GeneratedSQL(BaseModel):
    sql: str = Field(min_length=1, description="Single PostgreSQL SELECT query.")
    explanation: str = Field(
        min_length=1, description="Concise explanation of how the SQL answers the question."
    )


def generate_sql(
    question: str,
    *,
    settings: Settings | None = None,
    system_prompt: str | None = None,
) -> GeneratedSQL:
    """Generate structured SQL and explanation for a standalone question."""
    cfg = settings or get_settings()
    sys_prompt = system_prompt or build_schema_prompt(settings=cfg)
    prompt = f"Question: {question.strip()}\n\nWrite the PostgreSQL query and brief explanation."
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
    """Attempt one LLM repair of a SQL query given the database execution error."""
    cfg = settings or get_settings()
    sys_prompt = system_prompt or build_schema_prompt(settings=cfg)
    prompt = (
        f"Question: {question.strip()}\n\n"
        f"Previous SQL query failed during PostgreSQL execution:\n{failed_sql}\n\n"
        f"Database error:\n{error_text[:600]}\n\n"
        "Fix the SQL query using only columns from the 4 allowlisted views and return valid JSON."
    )
    return call_structured(
        GeneratedSQL,
        prompt,
        system=sys_prompt,
        settings=cfg,
    )
