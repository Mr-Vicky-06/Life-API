"""Streamlit AppTest integration and static isolation checks for dashboard/."""
from __future__ import annotations

import datetime
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import api_client
from dashboard import app as dashboard_app
from dashboard.api_client import START_API_HINT, DashboardAPIError

TEST_SECRET_KEY = "dashboard-apptest-secret-key-000"
APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"


@pytest.fixture(autouse=True)
def _clean_dashboard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_data.clear()
    monkeypatch.setenv("API_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("APP_API_KEY", TEST_SECRET_KEY)


def test_dashboard_static_isolation_and_cache_safety() -> None:
    dashboard_dir = Path("dashboard")
    py_files = sorted(dashboard_dir.rglob("*.py"))
    assert py_files, "Expected dashboard Python files."

    forbidden_snippets = (
        "import app",
        "from app",
        "unsafe_allow_html",
        "statsmodels",
        "sqlalchemy",
        "psycopg",
    )
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"Forbidden pattern {snippet!r} found in {py_file}"

    for fn in (
        dashboard_app.fetch_metrics_cached,
        dashboard_app.fetch_screen_time_cached,
        dashboard_app.fetch_search_cached,
    ):
        sig = inspect.signature(fn)
        assert "api_key" not in sig.parameters
        assert "app_api_key" not in sig.parameters


def _sample_metrics_rows() -> list[dict[str, Any]]:
    base = datetime.date.today() - datetime.timedelta(days=5)
    return [
        {
            "date": (base + datetime.timedelta(days=idx)).isoformat(),
            "sleep_hours": 7.0 + idx * 0.2,
            "sleep_score": 80 + idx,
            "deep_sleep_min": 90,
            "hrv_ms": 55,
            "resting_hr": 58,
            "steps": 8000 + idx * 500,
            "commits": idx + 1,
            "lines_added": 100 * (idx + 1),
            "pages_read": 20,
            "reading_minutes": 30,
            "screen_minutes": 180,
        }
        for idx in range(5)
    ]


def test_app_renders_kpis_charts_and_lazy_insight_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insight_calls: list[datetime.date | None] = []
    rows = _sample_metrics_rows()

    def fake_get_metrics(
        self: Any,
        from_date: datetime.date,
        to_date: datetime.date,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        return {"from_date": from_date.isoformat(), "to_date": to_date.isoformat(), "rows": rows}

    def fake_get_screen_time(
        self: Any,
        from_date: datetime.date,
        to_date: datetime.date,
    ) -> list[dict[str, Any]]:
        return [{"category": "coding", "minutes": 210}, {"category": "social", "minutes": 45}]

    def fake_get_daily_insight(
        self: Any,
        target_date: datetime.date | None = None,
    ) -> dict[str, Any]:
        insight_calls.append(target_date)
        return {
            "timestamp": (target_date or datetime.date.today()).isoformat(),
            "summary": "On that day, sleep averaged 7.5 hours.",
            "metrics": {"sleep_hours": 7.5, "commits": 3},
            "insights": "Steady progress aligned with good rest.",
        }

    monkeypatch.setattr(api_client.LifeAPIClient, "get_metrics", fake_get_metrics)
    monkeypatch.setattr(api_client.LifeAPIClient, "get_screen_time", fake_get_screen_time)
    monkeypatch.setattr(api_client.LifeAPIClient, "get_daily_insight", fake_get_daily_insight)

    at = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert len(at.exception) == 0
    assert len(at.metric) == 4
    data_captions = [c.value for c in at.caption if "Data: Synthetic demo data" in c.value]
    assert len(data_captions) >= 4
    assert any("Correlation, not causation" in c.value for c in at.caption)
    assert insight_calls == []

    monkeypatch.setenv("DATA_LABEL", "Custom labeled test dataset")
    st.cache_data.clear()
    at_custom = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert any("Data: Custom labeled test dataset" in c.value for c in at_custom.caption)

    # Daily insight must only run when the Generate insight button is explicitly clicked.
    generate_btn = next(b for b in at.button if b.label == "Generate insight")
    generate_btn.click().run()
    assert len(at.exception) == 0
    assert len(insight_calls) == 1
    assert any("Steady progress aligned with good rest." in t.value for t in at.text)


def test_app_shows_friendly_unreachable_and_401_banners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_unreachable(
        self: Any,
        from_date: datetime.date,
        to_date: datetime.date,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        raise DashboardAPIError(
            f"API unreachable. Start it with: `{START_API_HINT}`",
            code="unreachable",
            is_unreachable=True,
        )

    monkeypatch.setattr(api_client.LifeAPIClient, "get_metrics", raise_unreachable)
    at = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert len(at.exception) == 0
    assert any(START_API_HINT in err.value for err in at.error)
    assert all(TEST_SECRET_KEY not in err.value for err in at.error)

    st.cache_data.clear()

    def raise_401(
        self: Any,
        from_date: datetime.date,
        to_date: datetime.date,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        raise DashboardAPIError(
            "API key rejected, check APP_API_KEY in .env",
            status_code=401,
            code="unauthorized",
        )

    monkeypatch.setattr(api_client.LifeAPIClient, "get_metrics", raise_401)
    at_401 = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert len(at_401.exception) == 0
    assert any("API key rejected, check APP_API_KEY in .env" in err.value for err in at_401.error)


def test_app_chat_and_search_workflows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _sample_metrics_rows()
    captured_sessions: list[str | None] = []

    monkeypatch.setattr(
        api_client.LifeAPIClient,
        "get_metrics",
        lambda self, f, t, metrics=None: {
            "from_date": f.isoformat(),
            "to_date": t.isoformat(),
            "rows": rows,
        },
    )
    monkeypatch.setattr(
        api_client.LifeAPIClient,
        "get_screen_time",
        lambda self, f, t: [{"category": "coding", "minutes": 90}],
    )
    monkeypatch.setattr(
        api_client.LifeAPIClient,
        "search_notes",
        lambda self, q, top_k=8, source_type=None, date_from=None, date_to=None: [
            {
                "note_id": 10,
                "note_date": "2026-11-10",
                "source_type": "journal",
                "snippet": "Slept badly after late debugging <script>alert(1)</script>",
                "score": 0.9123,
            }
        ],
    )

    def fake_chat(self: Any, message: str, session_id: str | None = None) -> dict[str, Any]:
        captured_sessions.append(session_id)
        return {
            "answer": "You averaged 7.60 hours of sleep on commit days.",
            "model": "qwen2.5-coder:7b",
            "session_id": session_id,
            "steps": [
                {
                    "thought": "Query sleep vs commits in SQL.",
                    "action": "sql_query",
                    "action_input": {"question": message},
                    "observation": json.dumps(
                        {
                            "sql": "SELECT AVG(sleep_hours) FROM v_daily_summary WHERE commits > 0",
                            "columns": ["avg"],
                            "rows": [[7.6]],
                            "row_count": 1,
                        }
                    ),
                }
            ],
        }

    monkeypatch.setattr(api_client.LifeAPIClient, "post_agent_chat", fake_chat)

    at = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert len(at.exception) == 0

    at.text_input[0].input("slept badly")
    search_btn = next(b for b in at.button if b.label == "Search")
    search_btn.click().run()
    assert len(at.exception) == 0
    assert any("2026-11-10 | journal | score=0.9123" in c.value for c in at.caption)
    assert any("Slept badly after late debugging" in t.value for t in at.text)

    at.chat_input[0].set_value("Average sleep on commit days?").run()
    assert len(at.exception) == 0
    assert len(captured_sessions) == 1 and captured_sessions[0]
    assert any("averaged 7.60 hours of sleep" in t.value for t in at.text)
    assert any("SELECT AVG(sleep_hours)" in c.value for c in at.code)
