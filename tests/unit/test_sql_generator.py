"""Unit tests for Text-to-SQL generator unrequested-date-filter recovery (Q06 fix)."""
from __future__ import annotations

from unittest.mock import patch

from app.config import Settings
from app.sql_agent.generator import (
    GeneratedSQL,
    generate_sql,
    has_spurious_date_window,
    has_time_window_expression,
)


def _dummy_settings() -> Settings:
    return Settings(
        app_env="dev",
        app_api_key="test-key",
        database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life_test",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life_test",
    )


def test_time_window_detection_distinguishes_granular_grouping_from_ranges() -> None:
    assert has_time_window_expression("Show my weekly commit totals.") is False
    assert has_time_window_expression("Average sleep_hours grouped by month?") is False
    assert has_time_window_expression("Average sleep on days with commits > 0?") is False

    assert has_time_window_expression("What were my total commits in the last 30 days?") is True
    assert has_time_window_expression(
        "Total lines_added between 2026-10-01 and 2026-10-31?"
    ) is True
    assert has_time_window_expression("Steps in October 2026?") is True


def test_spurious_date_window_filter_triggers_only_on_unrequested_date_bounds() -> None:
    q_weekly = "Show my weekly commit totals."
    spurious_sql = (
        "SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits "
        "FROM v_daily_summary WHERE date > DATE '2026-11-23' - 7 GROUP BY 1 ORDER BY 1"
    )
    clean_sql = (
        "SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits "
        "FROM v_daily_summary GROUP BY 1 ORDER BY 1"
    )
    assert has_spurious_date_window(spurious_sql, q_weekly) is True
    assert has_spurious_date_window(clean_sql, q_weekly) is False

    # Valid EXTRACT(dow ...) weekday/weekend checks must NOT be flagged as spurious date windows.
    dow_sql = (
        "SELECT avg(sleep_hours) FROM v_daily_summary "
        "WHERE extract(dow FROM date) BETWEEN 1 AND 5"
    )
    assert has_spurious_date_window(
        dow_sql,
        "How does average sleep_hours compare on weekdays versus weekends?",
    ) is False

    # Legitimate explicit time window must NOT be flagged.
    assert has_spurious_date_window(
        spurious_sql,
        "Show my commit totals in the last 7 days.",
    ) is False


def test_generate_sql_regenerates_once_when_spurious_date_filter_emitted() -> None:
    spurious = GeneratedSQL(
        sql=(
            "SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits "
            "FROM v_daily_summary WHERE date > DATE '2026-11-23' - 7 GROUP BY 1"
        ),
        explanation="Weekly commits over 7 days.",
    )
    cleaned = GeneratedSQL(
        sql=(
            "SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits "
            "FROM v_daily_summary GROUP BY 1 ORDER BY 1"
        ),
        explanation="Weekly commit totals across all data.",
    )
    prompts_seen: list[str] = []

    def fake_call_structured(model_cls, prompt: str, **kwargs):
        prompts_seen.append(prompt)
        return spurious if len(prompts_seen) == 1 else cleaned

    with patch("app.sql_agent.generator.call_structured", side_effect=fake_call_structured):
        res = generate_sql("Show my weekly commit totals.", settings=_dummy_settings())

    assert len(prompts_seen) == 2
    assert "NO time window" in prompts_seen[1]
    assert res.sql == cleaned.sql
