"""Shared read-only time-series metrics service used by /v1/metrics and agent tools."""
from __future__ import annotations

import datetime
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import ro_engine
from app.gateway.exceptions import ValidationError
from app.schemas.metrics import MetricsResponse, ScreenTimeCategory
from app.sql_agent.executor import to_json_safe

MAX_RANGE_DAYS = 366


def validate_date_range(
    from_date: datetime.date,
    to_date: datetime.date,
    *,
    max_days: int = MAX_RANGE_DAYS,
) -> None:
    """Validate [from_date, to_date] bounds cleanly."""
    if from_date > to_date:
        raise ValidationError("'from' date must be on or before 'to' date.")
    if (to_date - from_date).days > max_days:
        raise ValidationError(f"Date range must not exceed {max_days} days.")

ALLOWED_METRIC_COLUMNS: dict[str, str] = {
    "sleep_hours": "sleep_hours",
    "sleep_score": "sleep_score",
    "deep_sleep_min": "deep_sleep_min",
    "hrv_ms": "hrv_ms",
    "resting_hr": "resting_hr",
    "steps": "steps",
    "commits": "commits",
    "lines_added": "lines_added",
    "pages_read": "pages_read",
    "reading_minutes": "reading_minutes",
    "screen_minutes": "screen_minutes",
}


def resolve_metric_names(metrics: Sequence[str] | str | None) -> list[str]:
    """Validate and deduplicate requested metric names against ALLOWED_METRIC_COLUMNS."""
    allowed_names = ", ".join(ALLOWED_METRIC_COLUMNS)

    if metrics is None:
        return list(ALLOWED_METRIC_COLUMNS.keys())

    if isinstance(metrics, str):
        if not metrics.strip():
            return list(ALLOWED_METRIC_COLUMNS.keys())
        requested = [part.strip() for part in metrics.split(",") if part.strip()]
    else:
        requested = [str(part).strip() for part in metrics if str(part).strip()]

    if not requested:
        raise ValidationError(f"No valid metric names provided. Allowed metrics: {allowed_names}.")

    unknown = [name for name in requested if name not in ALLOWED_METRIC_COLUMNS]
    if unknown:
        raise ValidationError(
            f"Unknown metric(s): {', '.join(unknown)}. Allowed metrics: {allowed_names}."
        )

    return list(dict.fromkeys(requested))


def query_metrics(
    *,
    from_date: datetime.date,
    to_date: datetime.date,
    metrics: Sequence[str] | str | None = None,
    ro_session: Session | None = None,
) -> MetricsResponse:
    """Query allowlisted metrics from v_daily_summary for [from_date, to_date] as life_ro."""
    validate_date_range(from_date, to_date)

    selected_metrics = resolve_metric_names(metrics)
    select_cols = ", ".join(ALLOWED_METRIC_COLUMNS[name] for name in selected_metrics)

    # SQL column list comes strictly from ALLOWED_METRIC_COLUMNS.
    stmt = text(
        f"SELECT date, {select_cols} FROM v_daily_summary "
        "WHERE date >= :from_date AND date <= :to_date ORDER BY date"
    )
    params = {"from_date": from_date, "to_date": to_date}

    if ro_session is not None:
        records = ro_session.execute(stmt, params).mappings().all()
    else:
        with Session(bind=ro_engine()) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            records = session.execute(stmt, params).mappings().all()

    rows: list[dict[str, float | int | str | None]] = []
    for rec in records:
        row_dict: dict[str, float | int | str | None] = {"date": to_json_safe(rec["date"])}
        for name in selected_metrics:
            col = ALLOWED_METRIC_COLUMNS[name]
            row_dict[name] = to_json_safe(rec[col])
        rows.append(row_dict)

    return MetricsResponse(from_date=from_date, to_date=to_date, rows=rows)


def query_screen_time(
    *,
    from_date: datetime.date,
    to_date: datetime.date,
    ro_session: Session | None = None,
) -> list[ScreenTimeCategory]:
    """Query screen-time category totals from v_screen_time ordered by minutes desc."""
    validate_date_range(from_date, to_date)

    stmt = text(
        "SELECT category, CAST(COALESCE(SUM(minutes), 0) AS INTEGER) AS minutes "
        "FROM v_screen_time "
        "WHERE date >= :from_date AND date <= :to_date "
        "GROUP BY category ORDER BY minutes DESC, category ASC"
    )
    params = {"from_date": from_date, "to_date": to_date}

    if ro_session is not None:
        records = ro_session.execute(stmt, params).mappings().all()
    else:
        with Session(bind=ro_engine()) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            records = session.execute(stmt, params).mappings().all()

    return [
        ScreenTimeCategory(category=str(rec["category"]), minutes=int(rec["minutes"]))
        for rec in records
    ]
