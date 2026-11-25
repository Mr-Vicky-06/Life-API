"""Pure KPI computation and Plotly chart builder functions (no DB or app.* imports)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import plotly.graph_objects as go

_PALETTE = {
    "accent": "#2563eb",
    "trend": "#dc2626",
    "bar": "#0f766e",
    "grid": "rgba(113, 113, 122, 0.16)",
    "text": "#71717a",
}


def _apply_base_layout(
    fig: go.Figure,
    *,
    height: int = 340,
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, -apple-system, sans-serif", color=_PALETTE["text"], size=12),
        margin=dict(l=12, r=12, t=28, b=16),
        xaxis=dict(title=xaxis_title, gridcolor=_PALETTE["grid"], zerolinecolor=_PALETTE["grid"]),
        yaxis=dict(title=yaxis_title, gridcolor=_PALETTE["grid"], zerolinecolor=_PALETTE["grid"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
    )
    return fig


def _empty_figure(message: str, *, height: int = 340) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=13, color=_PALETTE["text"]),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _apply_base_layout(fig, height=height)


def _extract_numeric(rows: list[dict[str, Any]], key: str) -> list[float]:
    vals: list[float] = []
    for row in rows:
        v = row.get(key)
        if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
            fval = float(v)
            if math.isfinite(fval):
                vals.append(fval)
    return vals


def _compute_mean_and_delta(
    cur_rows: list[dict[str, Any]],
    prev_rows: list[dict[str, Any]],
    key: str,
    decimals: int,
) -> dict[str, float | None]:
    cur_vals = _extract_numeric(cur_rows, key)
    prev_vals = _extract_numeric(prev_rows, key)
    cur_mean = round(sum(cur_vals) / len(cur_vals), decimals) if cur_vals else None
    prev_mean = round(sum(prev_vals) / len(prev_vals), decimals) if prev_vals else None
    delta = (
        round(cur_mean - prev_mean, decimals)
        if cur_mean is not None and prev_mean is not None
        else None
    )
    return {"value": cur_mean, "delta": delta}


def _compute_sum_and_delta(
    cur_rows: list[dict[str, Any]],
    prev_rows: list[dict[str, Any]],
    key: str,
) -> dict[str, int | None]:
    cur_vals = _extract_numeric(cur_rows, key)
    prev_vals = _extract_numeric(prev_rows, key)
    cur_sum = int(round(sum(cur_vals))) if cur_vals else None
    prev_sum = int(round(sum(prev_vals))) if prev_vals else None
    delta = cur_sum - prev_sum if cur_sum is not None and prev_sum is not None else None
    return {"value": cur_sum, "delta": delta}


def compute_period_kpis(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int | None]]:
    """Compute top-row KPIs and period-over-period deltas cleanly."""
    return {
        "avg_sleep_hours": _compute_mean_and_delta(current_rows, previous_rows, "sleep_hours", 2),
        "total_commits": _compute_sum_and_delta(current_rows, previous_rows, "commits"),
        "avg_steps": _compute_mean_and_delta(current_rows, previous_rows, "steps", 0),
        "total_reading_minutes": _compute_sum_and_delta(
            current_rows, previous_rows, "reading_minutes"
        ),
    }


def compute_sleep_commits_fit(
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[float], list[float], float | None, int, tuple[float, float] | None]:
    """Compute scatter arrays, Pearson r (corrcoef), and OLS fit (polyfit)."""
    dates: list[str] = []
    sleep_vals: list[float] = []
    commit_vals: list[float] = []

    for row in rows:
        sh = row.get("sleep_hours")
        cm = row.get("commits")
        if (
            sh is not None
            and cm is not None
            and isinstance(sh, (int, float))
            and isinstance(cm, (int, float))
            and not isinstance(sh, bool)
            and not isinstance(cm, bool)
        ):
            dates.append(str(row.get("date") or ""))
            sleep_vals.append(float(sh))
            commit_vals.append(float(cm))

    n = len(sleep_vals)
    if n < 2:
        return dates, sleep_vals, commit_vals, None, n, None

    x_arr = np.asarray(sleep_vals, dtype=float)
    y_arr = np.asarray(commit_vals, dtype=float)

    line_params: tuple[float, float] | None = None
    r_val: float | None = None

    if float(np.ptp(x_arr)) > 0.0:
        slope, intercept = np.polyfit(x_arr, y_arr, 1)
        line_params = (float(slope), float(intercept))
        if float(np.std(y_arr)) > 0.0:
            corr = float(np.corrcoef(x_arr, y_arr)[0, 1])
            if math.isfinite(corr):
                r_val = corr

    return dates, sleep_vals, commit_vals, r_val, n, line_params


def build_sleep_commits_figure(rows: list[dict[str, Any]]) -> tuple[go.Figure, str]:
    """Build Sleep vs Commits scatter figure with numpy OLS trendline and stats label."""
    dates, xs, ys, r_val, n, line_params = compute_sleep_commits_fit(rows)
    if n == 0:
        return _empty_figure("No sleep and commit pairs in the selected range."), "n = 0"

    stats_label = f"r = {r_val:.3f}, n = {n}" if r_val is not None else f"r = n/a, n = {n}"

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            name="Daily",
            customdata=dates,
            marker=dict(size=8, color=_PALETTE["accent"], opacity=0.82),
            hovertemplate=(
                "Date: %{customdata}<br>Sleep: %{x:.2f} h<br>Commits: %{y}<extra></extra>"
            ),
        )
    )

    if line_params is not None:
        slope, intercept = line_params
        x_min, x_max = min(xs), max(xs)
        fig.add_trace(
            go.Scatter(
                x=[x_min, x_max],
                y=[slope * x_min + intercept, slope * x_max + intercept],
                mode="lines",
                name="Trendline",
                line=dict(color=_PALETTE["trend"], width=2, dash="solid"),
                hoverinfo="skip",
            )
        )

    fig.update_layout(title=dict(text=stats_label, font=dict(size=12, color=_PALETTE["text"])))
    _apply_base_layout(fig, xaxis_title="Sleep (hours)", yaxis_title="GitHub Commits")
    return fig, stats_label


def build_steps_figure(rows: list[dict[str, Any]]) -> go.Figure:
    """Build Steps over time line chart."""
    dates: list[str] = []
    steps: list[float] = []
    for row in rows:
        st_val = row.get("steps")
        if st_val is not None and isinstance(st_val, (int, float)) and not isinstance(st_val, bool):
            dates.append(str(row.get("date") or ""))
            steps.append(float(st_val))

    if not dates:
        return _empty_figure("No step data in the selected range.")

    fig = go.Figure(
        go.Scatter(
            x=dates,
            y=steps,
            mode="lines+markers",
            name="Steps",
            line=dict(color=_PALETTE["accent"], width=2),
            marker=dict(size=5),
            hovertemplate="Date: %{x}<br>Steps: %{y:,.0f}<extra></extra>",
        )
    )
    return _apply_base_layout(fig, xaxis_title="Date", yaxis_title="Steps")


def build_screen_time_figure(categories: list[dict[str, Any]]) -> go.Figure:
    """Build Screen time by category bar chart ordered descending."""
    cats: list[str] = []
    mins: list[int] = []
    for item in categories:
        if isinstance(item, dict) and "category" in item and "minutes" in item:
            cats.append(str(item["category"]))
            mins.append(int(item["minutes"]))

    if not cats:
        return _empty_figure("No screen time data in the selected range.")

    fig = go.Figure(
        go.Bar(
            x=cats,
            y=mins,
            name="Minutes",
            marker=dict(color=_PALETTE["bar"]),
            hovertemplate="Category: %{x}<br>Minutes: %{y:,.0f}<extra></extra>",
        )
    )
    return _apply_base_layout(fig, xaxis_title="Category", yaxis_title="Minutes")
