"""Golden SQL verification tests (10 questions from TESTING.md §4 on seeded life_test DB)."""
from __future__ import annotations

import datetime
import json
import statistics
from collections import defaultdict
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import reset_engines
from app.main import app
from scripts.seed import generate_seed_data, seed_database

TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{TEST_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


def compute_golden_expected() -> dict[int, list[list[Any]]]:
    """Independently compute exact expected rows in pure Python from deterministic seed data."""
    data = generate_seed_data(end_date=SEED_END)
    health_by_date = {r["date"]: r for r in data["health"]}
    commits_by_date: dict[datetime.date, int] = defaultdict(int)
    for c in data["commits"]:
        commits_by_date[c["commit_date"]] += 1

    screen_by_date: dict[datetime.date, int] = defaultdict(int)
    cat_totals: dict[str, int] = defaultdict(int)
    for s in data["screen"]:
        screen_by_date[s["date"]] += s["minutes"]
        cat_totals[s["category"]] += s["minutes"]

    # Q1: Average sleep on days with commits > 0
    commit_sleeps = [
        health_by_date[d]["sleep_hours"]
        for d in health_by_date
        if commits_by_date[d] > 0
    ]
    exp_1 = [[round(sum(commit_sleeps) / len(commit_sleeps), 2)]]

    # Q2: Total commits last 30 days (2026-10-25..2026-11-23 inclusive -> end_date - 29)
    cutoff_30 = SEED_END - datetime.timedelta(days=29)
    exp_2 = [[sum(1 for c in data["commits"] if c["commit_date"] >= cutoff_30)]]

    # Q3: Day with most steps
    top_steps = max(data["health"], key=lambda r: r["steps"])
    exp_3 = [[top_steps["date"].isoformat(), top_steps["steps"]]]

    # Q4: Correlation between sleep_hours and commits
    ordered_dates = sorted(health_by_date)
    xs = [health_by_date[d]["sleep_hours"] for d in ordered_dates]
    ys = [commits_by_date[d] for d in ordered_dates]
    exp_4 = [[round(statistics.correlation(xs, ys), 3)]]

    # Q5: Average screen minutes on days sleep < 6
    low_sleep_dates = [d for d, r in health_by_date.items() if r["sleep_hours"] < 6.0]
    exp_5 = [[round(sum(screen_by_date[d] for d in low_sleep_dates) / len(low_sleep_dates), 2)]]

    # Q6: Weekly commit totals (including 0-commit weeks, matching v_daily_summary grouping)
    weekly: dict[datetime.date, int] = defaultdict(int)
    for d in ordered_dates:
        monday = d - datetime.timedelta(days=d.weekday())
        weekly[monday] += commits_by_date[d]
    exp_6 = [[w.isoformat(), cnt] for w, cnt in sorted(weekly.items())]

    # Q7: Total pages read last 14 days (2026-11-10..2026-11-23 inclusive -> end_date - 13)
    cutoff_14 = SEED_END - datetime.timedelta(days=13)
    exp_7 = [[sum(r["pages_read"] for r in data["reading"] if r["date"] >= cutoff_14)]]

    # Q8: Top 3 screen-time categories
    exp_8 = [[cat, total] for cat, total in sorted(cat_totals.items(), key=lambda kv: -kv[1])[:3]]

    # Q9: Average HRV on days with >=1 commit vs 0 commits
    hrv_with = [health_by_date[d]["hrv_ms"] for d in health_by_date if commits_by_date[d] >= 1]
    hrv_zero = [health_by_date[d]["hrv_ms"] for d in health_by_date if commits_by_date[d] == 0]
    exp_9 = [[round(sum(hrv_with) / len(hrv_with), 2), round(sum(hrv_zero) / len(hrv_zero), 2)]]

    # Q10: Longest streak of consecutive commit days
    commit_dates = sorted(d for d, cnt in commits_by_date.items() if cnt > 0)
    best = cur = 0
    prev = None
    for d in commit_dates:
        cur = (cur + 1) if (prev is not None and (d - prev).days == 1) else 1
        best = max(best, cur)
        prev = d
    exp_10 = [[best]]

    return {
        1: exp_1,
        2: exp_2,
        3: exp_3,
        4: exp_4,
        5: exp_5,
        6: exp_6,
        7: exp_7,
        8: exp_8,
        9: exp_9,
        10: exp_10,
    }


GOLDEN_CASES: list[tuple[int, str, str]] = [
    (
        1,
        "What was my average sleep on days with commits > 0?",
        "SELECT round(avg(sleep_hours)::numeric, 2) AS avg_sleep "
        "FROM v_daily_summary WHERE commits > 0",
    ),
    (
        2,
        "What were my total commits in the last 30 days?",
        "SELECT coalesce(sum(commits), 0) AS total_commits "
        "FROM v_daily_summary WHERE date >= DATE '2026-11-23' - 29",
    ),
    (
        3,
        "Which day did I have the most steps?",
        "SELECT date, steps FROM v_daily_summary ORDER BY steps DESC LIMIT 1",
    ),
    (
        4,
        "What is the correlation between sleep_hours and commits?",
        "SELECT round(corr(sleep_hours, commits)::numeric, 3) AS r FROM v_daily_summary",
    ),
    (
        5,
        "What were my average screen minutes on days sleep < 6?",
        "SELECT round(avg(screen_minutes)::numeric, 2) AS avg_screen "
        "FROM v_daily_summary WHERE sleep_hours < 6",
    ),
    (
        6,
        "Show my weekly commit totals.",
        "SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits "
        "FROM v_daily_summary GROUP BY 1 ORDER BY 1",
    ),
    (
        7,
        "What are the total pages read in the last 14 days?",
        "SELECT coalesce(sum(pages_read), 0) AS total_pages "
        "FROM v_reading WHERE date >= DATE '2026-11-23' - 13",
    ),
    (
        8,
        "What are my top 3 screen-time categories?",
        "SELECT category, sum(minutes) AS total "
        "FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
    ),
    (
        9,
        "What is my average HRV on days with >=1 commit vs 0 commits?",
        (
            "SELECT "
            "round(avg(hrv_ms) FILTER (WHERE commits >= 1)::numeric, 2) AS hrv_with_commits, "
            "round(avg(hrv_ms) FILTER (WHERE commits = 0)::numeric, 2) AS hrv_zero_commits "
            "FROM v_daily_summary"
        ),
    ),
    (
        10,
        "What is my longest streak of consecutive commit days?",
        (
            "WITH commit_days AS ("
            "SELECT date, date - (row_number() OVER (ORDER BY date))::int AS grp "
            "FROM v_daily_summary WHERE commits > 0"
            "), streaks AS ("
            "SELECT count(*) AS streak_len FROM commit_days GROUP BY grp"
            ") SELECT coalesce(max(streak_len), 0) AS longest_streak FROM streaks"
        ),
    ),
]


@pytest.fixture(scope="module")
def seeded_golden_db() -> Generator[dict[int, list[list[Any]]], None, None]:
    """Create fresh life_test database, run migrations, and seed deterministic dataset."""
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {TEST_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_RW_URL)
    command.upgrade(cfg, "head")

    settings = get_settings()
    orig = (
        settings.app_api_key,
        settings.database_url,
        settings.database_url_ro,
        settings.seed_end_date,
    )
    settings.app_api_key = "test-key"
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    settings.seed_end_date = SEED_END
    reset_engines()

    seed_database(end_date=SEED_END)
    expected = compute_golden_expected()

    yield expected

    (
        settings.app_api_key,
        settings.database_url,
        settings.database_url_ro,
        settings.seed_end_date,
    ) = orig
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


@pytest.mark.parametrize(
    ("qid", "question", "sql"),
    GOLDEN_CASES,
    ids=[f"golden_q{c[0]}" for c in GOLDEN_CASES],
)
def test_golden_question_pipeline(
    seeded_golden_db: dict[int, list[list[Any]]],
    monkeypatch: pytest.MonkeyPatch,
    qid: int,
    question: str,
    sql: str,
):
    """Stub LLM returns expected SQL -> full /v1/query pipeline produces exact expected rows."""

    def fake_litellm_completion(**kwargs):
        resp_fmt = kwargs.get("response_format")
        if resp_fmt and resp_fmt.get("type") == "json_object":
            payload = json.dumps({"sql": sql, "explanation": f"Golden SQL for Q{qid}."})
        else:
            payload = f"Computed result summary for golden question {qid}."
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(completion_tokens=20),
        )

    monkeypatch.setattr("app.gateway.llm.litellm.completion", fake_litellm_completion)

    client = TestClient(app)
    resp = client.post(
        "/v1/query",
        headers={"X-API-Key": "test-key"},
        json={"question": question},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == seeded_golden_db[qid]
    assert body["row_count"] == len(seeded_golden_db[qid])
