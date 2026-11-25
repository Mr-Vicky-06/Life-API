"""Pydantic-validated tool definitions and safe execution dispatcher for the ReAct agent."""
from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.gateway.exceptions import GatewayException
from app.gateway.guardrails import check_input
from app.gateway.pii import redact_all
from app.metrics import ALLOWED_METRIC_COLUMNS, query_metrics
from app.rag.hybrid import hybrid_search
from app.sql_agent.executor import execute_readonly_sql
from app.sql_agent.generator import generate_sql, repair_sql
from app.sql_agent.validator import validate_sql

logger = logging.getLogger(__name__)

MAX_SQL_OBS_ROWS = 20


class SQLQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)


class SearchNotesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=300)
    top_k: int = Field(default=5, ge=1, le=8)
    source_type: Literal["journal", "reading_note", "commit_message"] | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None


class GetMetricsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_date: datetime.date = Field(alias="from")
    to_date: datetime.date = Field(alias="to")
    metrics: list[str] | None = None


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "sql_query",
        "description": (
            "Run the read-only Text-to-SQL pipeline on a natural-language question "
            "(NEVER raw SQL). Best for aggregates, averages, correlations, rankings, "
            "counts, or streaks across all dates or filtered conditions."
        ),
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "minLength": 3, "maxLength": 500}},
            "required": ["question"],
        },
    },
    {
        "name": "search_notes",
        "description": (
            "Hybrid semantic + full-text search over personal journal notes, reading notes, "
            "and git commit messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 300},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
                "source_type": {
                    "type": "string",
                    "enum": ["journal", "reading_note", "commit_message"],
                },
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_metrics",
        "description": (
            "Fetch raw day-by-day rows from v_daily_summary for an explicit [from, to] date "
            "range (max 366 days; does NOT aggregate or filter by conditions — use sql_query for "
            f"averages, totals, or conditional queries). Allowed metrics: "
            f"{', '.join(ALLOWED_METRIC_COLUMNS)}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from": {"type": "string", "format": "date"},
                "to": {"type": "string", "format": "date"},
                "metrics": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(ALLOWED_METRIC_COLUMNS)},
                },
            },
            "required": ["from", "to"],
        },
    },
]


def _run_sql_query(args: SQLQueryArgs, settings: Settings) -> str:
    check_input(args.question, max_length=500)
    generated = generate_sql(args.question, settings=settings)
    validated_sql = validate_sql(generated.sql)

    try:
        res = execute_readonly_sql(validated_sql)
    except SQLAlchemyError as first_err:
        repaired = repair_sql(
            args.question,
            validated_sql,
            str(first_err),
            settings=settings,
        )
        validated_sql = validate_sql(repaired.sql)
        res = execute_readonly_sql(validated_sql)

    return json.dumps(
        {
            "sql": validated_sql,
            "columns": res.columns,
            "rows": res.rows[:MAX_SQL_OBS_ROWS],
            "row_count": res.row_count,
        },
        ensure_ascii=False,
    )


def _run_search_notes(args: SearchNotesArgs, settings: Settings) -> str:
    hits = hybrid_search(
        query=args.query,
        top_k=args.top_k,
        date_from=args.date_from,
        date_to=args.date_to,
        source_type=args.source_type,
    )
    payload = [
        {
            "note_date": hit.note_date.isoformat(),
            "source_type": hit.source_type,
            "snippet": hit.snippet,
        }
        for hit in hits
    ]
    return json.dumps(payload, ensure_ascii=False)


def _run_get_metrics(args: GetMetricsArgs, settings: Settings) -> str:
    resp = query_metrics(
        from_date=args.from_date,
        to_date=args.to_date,
        metrics=args.metrics,
    )
    return json.dumps(
        {
            "from_date": resp.from_date.isoformat(),
            "to_date": resp.to_date.isoformat(),
            "rows": resp.rows,
        },
        ensure_ascii=False,
    )


_TOOL_REGISTRY: dict[str, tuple[type[BaseModel], Any]] = {
    "sql_query": (SQLQueryArgs, _run_sql_query),
    "search_notes": (SearchNotesArgs, _run_search_notes),
    "get_metrics": (GetMetricsArgs, _run_get_metrics),
}


def execute_tool(
    action: str,
    action_input: Any,
    *,
    settings: Settings | None = None,
) -> tuple[str, bool]:
    """Validate tool arguments with Pydantic and execute tool safely.

    Never raises: invalid arguments, unknown actions, and runtime failures
    are returned cleanly as ``("Error: ...", False)`` observations.
    """
    cfg = settings or get_settings()
    entry = _TOOL_REGISTRY.get(action)
    if entry is None:
        return (
            f"Error: unknown tool '{action}'. "
            "Choose sql_query, search_notes, get_metrics, or final.",
            False,
        )

    arg_model, runner = entry
    if not isinstance(action_input, dict):
        return (f"Error ({action}): action_input must be a JSON object.", False)

    try:
        validated_args = arg_model.model_validate(action_input)
        output = runner(validated_args, cfg)
        return output, True
    except PydanticValidationError as exc:
        return (f"Error ({action}): invalid arguments: {exc.errors()}", False)
    except GatewayException as exc:
        return (f"Error ({action}): {exc.message}", False)
    except Exception as exc:
        secrets = [s for s in (cfg.app_api_key, cfg.github_token) if s]
        safe_msg = redact_all(
            str(exc)[:300],
            literal_secrets=secrets,
            health_id_regex=getattr(cfg, "health_id_regex", None),
        )
        return (f"Error ({action}): {type(exc).__name__}: {safe_msg}", False)
