"""Read-only time-series metrics route (/v1/metrics) querying v_daily_summary."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_ro_session
from app.deps import verify_api_key
from app.gateway.exceptions import ValidationError
from app.schemas.metrics import MetricsResponse
from app.sql_agent.executor import to_json_safe

router = APIRouter(prefix="/v1", tags=["metrics"])

MAX_RANGE_DAYS = 366

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


def _parse_metrics_param(metrics_raw: str | None) -> list[str]:
    """Validate and resolve requested metric names using a strict column allowlist."""
    allowed_names = ", ".join(ALLOWED_METRIC_COLUMNS)
    if metrics_raw is None or not metrics_raw.strip():
        return list(ALLOWED_METRIC_COLUMNS.keys())

    requested = [part.strip() for part in metrics_raw.split(",") if part.strip()]
    if not requested:
        raise ValidationError(f"No valid metric names provided. Allowed metrics: {allowed_names}.")

    unknown = [name for name in requested if name not in ALLOWED_METRIC_COLUMNS]
    if unknown:
        raise ValidationError(
            f"Unknown metric(s): {', '.join(unknown)}. Allowed metrics: {allowed_names}."
        )

    return list(dict.fromkeys(requested))


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
def get_metrics(
    from_date: datetime.date = Query(alias="from"),
    to_date: datetime.date = Query(alias="to"),
    metrics: str | None = Query(default=None),
    ro_session: Session = Depends(get_ro_session),
) -> MetricsResponse:
    """Return daily metric rows from v_daily_summary for [from_date, to_date]."""
    if from_date > to_date:
        raise ValidationError("'from' date must be on or before 'to' date.")
    if (to_date - from_date).days > MAX_RANGE_DAYS:
        raise ValidationError(f"Date range must not exceed {MAX_RANGE_DAYS} days.")

    selected_metrics = _parse_metrics_param(metrics)
    select_cols = ", ".join(ALLOWED_METRIC_COLUMNS[name] for name in selected_metrics)

    # SQL identifier list is strictly constructed from ALLOWED_METRIC_COLUMNS.
    stmt = text(
        f"SELECT date, {select_cols} FROM v_daily_summary "
        "WHERE date >= :from_date AND date <= :to_date ORDER BY date"
    )
    records = ro_session.execute(
        stmt,
        {"from_date": from_date, "to_date": to_date},
    ).mappings()

    rows: list[dict[str, float | int | str | None]] = []
    for rec in records:
        row_dict: dict[str, float | int | str | None] = {"date": to_json_safe(rec["date"])}
        for name in selected_metrics:
            col = ALLOWED_METRIC_COLUMNS[name]
            row_dict[name] = to_json_safe(rec[col])
        rows.append(row_dict)

    return MetricsResponse(from_date=from_date, to_date=to_date, rows=rows)
