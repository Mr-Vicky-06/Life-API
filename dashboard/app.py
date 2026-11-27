"""Personal Life Intelligence Streamlit dashboard talking strictly to the FastAPI backend."""
from __future__ import annotations

import datetime
import json
import re
import time
import uuid
from typing import Any

import streamlit as st

from dashboard.api_client import START_API_HINT, DashboardAPIError, LifeAPIClient
from dashboard.charts import (
    build_screen_time_figure,
    build_sleep_commits_figure,
    build_steps_figure,
    compute_period_kpis,
)
from dashboard.config import get_dashboard_config

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SOURCE_OPTIONS = ["all", "journal", "reading_note", "commit_message"]


def _build_client(api_url: str | None = None) -> LifeAPIClient:
    """Create a fresh API client using env/runtime config (never cached as a key)."""
    cfg = get_dashboard_config()
    return LifeAPIClient(api_url=api_url or cfg.api_url, api_key=cfg.app_api_key)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_metrics_cached(
    api_url: str,
    from_date: datetime.date,
    to_date: datetime.date,
) -> dict[str, Any]:
    """Fetch daily metrics with TTL=60s; never includes api_key in cache parameters."""
    return _build_client(api_url).get_metrics(from_date, to_date)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_screen_time_cached(
    api_url: str,
    from_date: datetime.date,
    to_date: datetime.date,
) -> list[dict[str, Any]]:
    """Fetch screen-time category totals with TTL=60s (api_key excluded from cache key)."""
    return _build_client(api_url).get_screen_time(from_date, to_date)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_search_cached(
    api_url: str,
    query: str,
    top_k: int,
    source_type: str | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> list[dict[str, Any]]:
    """Fetch hybrid note search results with TTL=60s (api_key excluded from cache key)."""
    return _build_client(api_url).search_notes(
        query,
        top_k=top_k,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
    )


def _render_api_error(exc: DashboardAPIError) -> None:
    """Render concise, user-safe API errors without secrets or stack traces."""
    if exc.is_unreachable and START_API_HINT not in exc.message:
        st.error(f"{exc.message} Start the API with: `{START_API_HINT}`")
        return
    if exc.status_code == 401:
        st.error("API key rejected, check APP_API_KEY in .env")
        return
    st.error(exc.message)


def _parse_iso_date(raw: Any) -> datetime.date | None:
    if isinstance(raw, datetime.date) and not isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def resolve_date_bounds(
    rows: list[dict[str, Any]],
) -> tuple[datetime.date | None, datetime.date | None, datetime.date | None, datetime.date | None]:
    """Compute (min_avail, max_avail, default_start, default_end) from /v1/metrics rows."""
    parsed = sorted(d for row in rows if (d := _parse_iso_date(row.get("date"))) is not None)
    if not parsed:
        return None, None, None, None
    min_avail = parsed[0]
    max_avail = parsed[-1]
    default_start = max(min_avail, max_avail - datetime.timedelta(days=29))
    return min_avail, max_avail, default_start, max_avail


def _normalize_date_range(
    selected: Any,
    default_start: datetime.date,
    default_end: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    if isinstance(selected, tuple | list):
        if len(selected) >= 2:
            start_d, end_d = selected[0], selected[1]
        elif len(selected) == 1:
            start_d = end_d = selected[0]
        else:
            start_d, end_d = default_start, default_end
    elif isinstance(selected, datetime.date):
        start_d = end_d = selected
    else:
        start_d, end_d = default_start, default_end
    return (end_d, start_d) if start_d > end_d else (start_d, end_d)


def ensure_chat_session_id() -> str:
    """Return a validated UUID session_id stored in st.session_state."""
    existing = str(st.session_state.get("chat_session_id", ""))
    if not _SESSION_ID_RE.fullmatch(existing):
        existing = str(uuid.uuid4())
        st.session_state["chat_session_id"] = existing
    return existing


def _extract_step_sql(step: dict[str, Any]) -> str | None:
    """Extract SQL text from a sql_query step observation or action_input if present."""
    if step.get("action") != "sql_query":
        return None
    obs = step.get("observation")
    if isinstance(obs, str) and obs.strip().startswith("{"):
        try:
            parsed = json.loads(obs)
            if isinstance(parsed, dict) and isinstance(parsed.get("sql"), str):
                return parsed["sql"]
        except ValueError:
            pass
    action_input = step.get("action_input")
    if isinstance(action_input, dict) and isinstance(action_input.get("sql"), str):
        return action_input["sql"]
    return None


def _render_overview_tab(
    api_url: str,
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    bootstrap_error: DashboardAPIError | None,
    data_label: str = "Synthetic demo data",
) -> None:
    if bootstrap_error is not None:
        st.info("Resolve the API connection error above to load metrics and charts.")
        return
    if start_date is None or end_date is None:
        st.info("No metric data available in the last 366 days.")
        return

    span_days = (end_date - start_date).days + 1
    prev_end = start_date - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=span_days - 1)

    try:
        current_payload = fetch_metrics_cached(api_url, start_date, end_date)
        previous_payload = fetch_metrics_cached(api_url, prev_start, prev_end)
        screen_rows = fetch_screen_time_cached(api_url, start_date, end_date)
    except DashboardAPIError as exc:
        _render_api_error(exc)
        return

    current_rows = list(current_payload.get("rows", []))
    previous_rows = list(previous_payload.get("rows", []))
    if not current_rows:
        st.info("No metric rows recorded for the selected date range.")
        return

    kpis = compute_period_kpis(current_rows, previous_rows)
    sleep_kpi = kpis["avg_sleep_hours"]
    commits_kpi = kpis["total_commits"]
    steps_kpi = kpis["avg_steps"]
    reading_kpi = kpis["total_reading_minutes"]

    cols = st.columns(4)
    cols[0].metric(
        "Avg Sleep (h)",
        f"{sleep_kpi['value']:.2f} h" if sleep_kpi["value"] is not None else "N/A",
        delta=f"{sleep_kpi['delta']:+.2f} h" if sleep_kpi["delta"] is not None else None,
    )
    cols[1].metric(
        "Total Commits",
        f"{int(commits_kpi['value'] or 0):,}",
        delta=f"{int(commits_kpi['delta']):+d}" if commits_kpi["delta"] is not None else None,
    )
    cols[2].metric(
        "Avg Steps",
        f"{steps_kpi['value']:,.0f}" if steps_kpi["value"] is not None else "N/A",
        delta=f"{steps_kpi['delta']:+.0f}" if steps_kpi["delta"] is not None else None,
    )
    cols[3].metric(
        "Total Reading (min)",
        f"{int(reading_kpi['value'] or 0):,} min",
        delta=(
            f"{int(reading_kpi['delta']):+d} min"
            if reading_kpi["delta"] is not None
            else None
        ),
    )

    chart_left, chart_right = st.columns(2)
    with chart_left:
        sleep_fig, stats_label = build_sleep_commits_figure(current_rows)
        st.plotly_chart(sleep_fig, width="stretch")
        st.caption(f"Correlation, not causation ({stats_label}) | Data: {data_label}")
    with chart_right:
        steps_fig = build_steps_figure(current_rows)
        st.plotly_chart(steps_fig, width="stretch")
        st.caption(f"Data: {data_label}")

    screen_fig = build_screen_time_figure(screen_rows)
    st.plotly_chart(screen_fig, width="stretch")
    st.caption(f"Data: {data_label}")


def _render_daily_insight_tab(
    api_url: str,
    min_avail: datetime.date | None,
    max_avail: datetime.date | None,
) -> None:
    st.subheader("Daily Insight")
    default_day = max_avail or datetime.date.today()
    date_kwargs: dict[str, Any] = {
        "label": "Insight date",
        "value": default_day,
        "key": "insight_date_input",
    }
    if min_avail is not None and max_avail is not None:
        date_kwargs["min_value"] = min_avail
        date_kwargs["max_value"] = max_avail
    selected_date = st.date_input(**date_kwargs)

    if st.button("Generate insight", type="primary", key="generate_insight_btn"):
        with st.spinner("Generating daily insight..."):
            try:
                result = _build_client(api_url).get_daily_insight(selected_date)
            except DashboardAPIError as exc:
                st.session_state["daily_insight_error"] = exc
                st.session_state["daily_insight_result"] = None
            else:
                st.session_state["daily_insight_error"] = None
                st.session_state["daily_insight_result"] = result

    insight_err = st.session_state.get("daily_insight_error")
    if isinstance(insight_err, DashboardAPIError):
        _render_api_error(insight_err)

    insight_data = st.session_state.get("daily_insight_result")
    if isinstance(insight_data, dict):
        with st.container(border=True):
            st.caption(f"Date: {insight_data.get('timestamp', selected_date)}")
            st.write("Summary")
            st.text(str(insight_data.get("summary", "")))
            st.write("Insight")
            st.text(str(insight_data.get("insights", "")))

            metrics_map = insight_data.get("metrics") or {}
            if isinstance(metrics_map, dict) and metrics_map:
                items = list(metrics_map.items())
                metric_cols = st.columns(min(4, len(items)))
                for idx, (name, val) in enumerate(items):
                    formatted = f"{val:.2f}" if isinstance(val, float) else str(val)
                    metric_cols[idx % len(metric_cols)].metric(name, formatted)


def _render_search_tab(
    api_url: str,
    min_avail: datetime.date | None,
    max_avail: datetime.date | None,
    default_start: datetime.date | None,
    default_end: datetime.date | None,
) -> None:
    st.subheader("Search Notes")
    with st.form("search_notes_form"):
        query = st.text_input(
            "Search query",
            placeholder="e.g. slept badly",
            key="search_query_input",
        )
        col_src, col_toggle = st.columns(2)
        with col_src:
            source_choice = st.selectbox(
                "Source type",
                options=_SOURCE_OPTIONS,
                key="search_source_select",
            )
        with col_toggle:
            apply_dates = st.checkbox(
                "Filter by date range",
                value=False,
                key="search_apply_dates",
            )

        today = datetime.date.today()
        d_from_default = default_start or (today - datetime.timedelta(days=29))
        d_to_default = default_end or today
        col_from, col_to = st.columns(2)
        with col_from:
            date_from_val = st.date_input(
                "From date",
                value=d_from_default,
                min_value=min_avail,
                max_value=max_avail,
                key="search_date_from",
            )
        with col_to:
            date_to_val = st.date_input(
                "To date",
                value=d_to_default,
                min_value=min_avail,
                max_value=max_avail,
                key="search_date_to",
            )
        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        cleaned_query = query.strip()
        if len(cleaned_query) < 2:
            st.warning("Enter at least 2 characters to search.")
        else:
            src = None if source_choice == "all" else source_choice
            d_from = date_from_val if apply_dates else None
            d_to = date_to_val if apply_dates else None
            try:
                hits = fetch_search_cached(api_url, cleaned_query, 8, src, d_from, d_to)
            except DashboardAPIError as exc:
                st.session_state["search_error"] = exc
                st.session_state["search_results"] = None
            else:
                st.session_state["search_error"] = None
                st.session_state["search_results"] = hits

    search_err = st.session_state.get("search_error")
    if isinstance(search_err, DashboardAPIError):
        _render_api_error(search_err)

    hits = st.session_state.get("search_results")
    if hits is None:
        return
    if not hits:
        st.info("No matching notes found.")
        return

    for hit in hits:
        with st.container(border=True):
            score = hit.get("score")
            score_txt = f"{score:.4f}" if isinstance(score, int | float) else str(score)
            st.caption(
                f"{hit.get('note_date', '')} | {hit.get('source_type', '')} | "
                f"score={score_txt}"
            )
            st.text(str(hit.get("snippet", "")))


def _render_chat_entry(entry: dict[str, Any]) -> None:
    role = str(entry.get("role", "assistant"))
    with st.chat_message(role):
        if role == "user":
            st.text(str(entry.get("content", "")))
            return

        err = entry.get("error")
        if isinstance(err, DashboardAPIError):
            _render_api_error(err)
            return

        st.text(str(entry.get("content", "")))
        steps = entry.get("steps") or []
        latency_ms = entry.get("latency_ms")
        lat_txt = f"{latency_ms} ms" if latency_ms is not None else "N/A"
        with st.expander(f"Steps ({len(steps)}) | Latency: {lat_txt}", expanded=False):
            if not steps:
                st.caption("No intermediate tool steps recorded.")
            for idx, step in enumerate(steps, start=1):
                action = step.get("action", "")
                thought = step.get("thought", "")
                st.write(f"Step {idx}: `{action}`")
                if thought:
                    st.text(str(thought))
                sql = _extract_step_sql(step)
                if sql:
                    st.code(sql, language="sql")


def _render_chat_tab(api_url: str) -> None:
    st.subheader("AI Chat")
    session_id = ensure_chat_session_id()
    st.caption(f"Session ID: {session_id}")
    history: list[dict[str, Any]] = st.session_state.setdefault("chat_history", [])

    for entry in history:
        _render_chat_entry(entry)

    prompt = st.chat_input(
        "Ask about sleep, commits, steps, reading, or personal notes...",
        key="agent_chat_input",
    )
    if prompt and prompt.strip():
        cleaned = prompt.strip()
        user_entry = {"role": "user", "content": cleaned}
        history.append(user_entry)
        _render_chat_entry(user_entry)

        started = time.perf_counter()
        with st.spinner("Thinking..."):
            try:
                reply = _build_client(api_url).post_agent_chat(
                    cleaned,
                    session_id=session_id,
                )
            except DashboardAPIError as exc:
                assistant_entry = {
                    "role": "assistant",
                    "content": "",
                    "steps": [],
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": exc,
                }
            else:
                assistant_entry = {
                    "role": "assistant",
                    "content": str(reply.get("answer", "")),
                    "steps": list(reply.get("steps", [])),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": None,
                }
        history.append(assistant_entry)
        _render_chat_entry(assistant_entry)


def main() -> None:
    """Render the multi-section Personal Life Intelligence dashboard."""
    st.set_page_config(page_title="Personal Life Intelligence", layout="wide")
    st.title("Personal Life Intelligence")

    cfg = get_dashboard_config()
    api_url = cfg.api_url
    today = datetime.date.today()
    window_start = today - datetime.timedelta(days=366)

    bootstrap_error: DashboardAPIError | None = None
    available_rows: list[dict[str, Any]] = []
    try:
        avail_payload = fetch_metrics_cached(api_url, window_start, today)
        available_rows = list(avail_payload.get("rows", []))
    except DashboardAPIError as exc:
        bootstrap_error = exc
        _render_api_error(exc)

    min_avail, max_avail, default_start, default_end = resolve_date_bounds(available_rows)

    st.sidebar.header("Dataset")
    st.sidebar.caption(f"Data: {cfg.data_label}")

    st.sidebar.header("Filters")
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    if min_avail is not None and max_avail is not None and default_start and default_end:
        selected = st.sidebar.date_input(
            "Date range",
            value=(default_start, default_end),
            min_value=min_avail,
            max_value=max_avail,
            key="sidebar_date_range",
        )
        start_date, end_date = _normalize_date_range(selected, default_start, default_end)
        st.sidebar.caption(f"Available data: {min_avail.isoformat()} to {max_avail.isoformat()}")
    elif bootstrap_error is None:
        st.sidebar.info("No data available in the last 366 days.")

    tab_overview, tab_insight, tab_search, tab_chat = st.tabs(
        ["Overview", "Daily Insight", "Search Notes", "AI Chat"]
    )
    with tab_overview:
        _render_overview_tab(api_url, start_date, end_date, bootstrap_error, cfg.data_label)
    with tab_insight:
        _render_daily_insight_tab(api_url, min_avail, max_avail)
    with tab_search:
        _render_search_tab(api_url, min_avail, max_avail, default_start, default_end)
    with tab_chat:
        _render_chat_tab(api_url)


main()
