"""Read-only time-series metrics route (/v1/metrics) querying v_daily_summary."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_ro_session
from app.deps import verify_api_key
from app.metrics import ALLOWED_METRIC_COLUMNS, MAX_RANGE_DAYS, query_metrics
from app.schemas.metrics import MetricsResponse

router = APIRouter(prefix="/v1", tags=["metrics"])

__all__ = ["ALLOWED_METRIC_COLUMNS", "MAX_RANGE_DAYS", "get_metrics", "router"]


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
    return query_metrics(
        from_date=from_date,
        to_date=to_date,
        metrics=metrics,
        ro_session=ro_session,
    )
