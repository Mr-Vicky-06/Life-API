"""Unit tests for dashboard Plotly figures, OLS trendlines, and period KPI math."""
from __future__ import annotations

import pytest

from dashboard.charts import (
    build_screen_time_figure,
    build_sleep_commits_figure,
    build_steps_figure,
    compute_period_kpis,
    compute_sleep_commits_fit,
)


def test_compute_sleep_commits_fit_linear_relationship() -> None:
    rows = [
        {"date": "2026-11-01", "sleep_hours": 6.0, "commits": 1},
        {"date": "2026-11-02", "sleep_hours": 7.0, "commits": 3},
        {"date": "2026-11-03", "sleep_hours": 8.0, "commits": 5},
    ]
    dates, x_vals, y_vals, r_val, count, fit = compute_sleep_commits_fit(rows)
    assert dates == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert x_vals == [6.0, 7.0, 8.0]
    assert y_vals == [1.0, 3.0, 5.0]
    assert count == 3
    assert r_val == pytest.approx(1.0, abs=1e-6)
    assert fit is not None
    slope, intercept = fit
    assert slope == pytest.approx(2.0, abs=1e-6)
    assert intercept == pytest.approx(-11.0, abs=1e-6)


def test_compute_sleep_commits_fit_handles_constant_and_missing_rows() -> None:
    rows = [
        {"date": "2026-11-01", "sleep_hours": 7.0, "commits": 2},
        {"date": "2026-11-02", "sleep_hours": 7.0, "commits": 4},
        {"date": "2026-11-03", "sleep_hours": None, "commits": 5},
    ]
    _, _, _, r_val, count, fit = compute_sleep_commits_fit(rows)
    assert count == 2
    assert r_val is None
    assert fit is None


def test_compute_period_kpis_values_and_deltas() -> None:
    current = [
        {"sleep_hours": 8.0, "commits": 4, "steps": 9000, "reading_minutes": 30},
        {"sleep_hours": 6.0, "commits": 2, "steps": 7000, "reading_minutes": 45},
    ]
    previous = [
        {"sleep_hours": 6.0, "commits": 1, "steps": 6000, "reading_minutes": 20},
        {"sleep_hours": 6.0, "commits": 2, "steps": 6000, "reading_minutes": 20},
    ]
    kpis = compute_period_kpis(current, previous)
    assert kpis["avg_sleep_hours"]["value"] == pytest.approx(7.0)
    assert kpis["avg_sleep_hours"]["delta"] == pytest.approx(1.0)
    assert kpis["total_commits"]["value"] == 6
    assert kpis["total_commits"]["delta"] == 3
    assert kpis["avg_steps"]["value"] == pytest.approx(8000.0)
    assert kpis["avg_steps"]["delta"] == pytest.approx(2000.0)
    assert kpis["total_reading_minutes"]["value"] == 75
    assert kpis["total_reading_minutes"]["delta"] == 35

    empty_prev = compute_period_kpis(current, [])
    assert empty_prev["avg_sleep_hours"]["delta"] is None
    assert empty_prev["total_commits"]["delta"] is None


def test_figure_builders_handle_normal_and_empty_inputs() -> None:
    rows = [
        {"date": "2026-11-01", "sleep_hours": 6.5, "commits": 2, "steps": 7500},
        {"date": "2026-11-02", "sleep_hours": 8.0, "commits": 6, "steps": 10200},
    ]
    scatter_fig, stats_label = build_sleep_commits_figure(rows)
    assert "n = 2" in stats_label
    assert "r = 1.000" in stats_label
    assert len(scatter_fig.data) == 2

    empty_fig, empty_label = build_sleep_commits_figure([])
    assert empty_label == "n = 0"
    assert len(empty_fig.data) == 0

    steps_fig = build_steps_figure(rows)
    assert len(steps_fig.data) == 1
    assert len(build_steps_figure([]).data) == 0

    screen_fig = build_screen_time_figure(
        [{"category": "coding", "minutes": 180}, {"category": "social", "minutes": 40}]
    )
    assert len(screen_fig.data) == 1
    assert len(build_screen_time_figure([]).data) == 0
