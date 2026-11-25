"""Benchmark (NOT a gate): evaluate ReAct tool selection & accuracy across 15 questions."""
from __future__ import annotations

import datetime
import statistics
import time
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.react import clear_sessions, run_react_agent
from app.config import get_settings
from app.db import reset_engines, ro_engine
from scripts.seed import seed_database

BENCH_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
BENCH_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{BENCH_DB_NAME}"
BENCH_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{BENCH_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


def _setup_bench_db() -> None:
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {BENCH_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {BENCH_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {BENCH_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {BENCH_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", BENCH_RW_URL)
    command.upgrade(cfg, "head")

    settings = get_settings()
    settings.database_url = BENCH_RW_URL
    settings.database_url_ro = BENCH_RO_URL
    settings.seed_end_date = SEED_END
    settings.reference_date = SEED_END
    reset_engines()
    seed_database(end_date=SEED_END)


def _cleanup_bench_db() -> None:
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {BENCH_DB_NAME} WITH (FORCE);")


def _compute_expected_values() -> dict[str, list[str]]:
    with Session(bind=ro_engine()) as sess:
        avg_sleep_commit = float(
            sess.execute(
                text("SELECT round(avg(sleep_hours), 2) FROM v_daily_summary WHERE commits > 0")
            ).scalar_one()
        )
        max_steps_row = sess.execute(
            text("SELECT date, steps FROM v_daily_summary ORDER BY steps DESC LIMIT 1")
        ).one()
        corr_val = float(
            sess.execute(
                text("SELECT round(corr(sleep_hours, commits)::numeric, 3) FROM v_daily_summary")
            ).scalar_one()
        )
        streak_val = int(
            sess.execute(
                text(
                    "WITH c AS (SELECT date, date - (row_number() OVER (ORDER BY date))::int AS g "
                    "FROM v_daily_summary WHERE commits > 0) "
                    "SELECT coalesce(max(cnt), 0) FROM (SELECT count(*) AS cnt FROM c GROUP BY g) s"
                )
            ).scalar_one()
        )
        hrv_row = sess.execute(
            text(
                "SELECT round(avg(hrv_ms) FILTER (WHERE commits > 0), 2), "
                "round(avg(hrv_ms) FILTER (WHERE commits = 0), 2) FROM v_daily_summary"
            )
        ).one()
        m1 = sess.execute(
            text(
                "SELECT sleep_hours, commits FROM v_daily_summary "
                "WHERE date = '2026-11-02'"
            )
        ).one()
        m2 = sess.execute(
            text(
                "SELECT steps, screen_minutes FROM v_daily_summary "
                "WHERE date = '2026-11-23'"
            )
        ).one()
        m3_rows = sess.execute(
            text(
                "SELECT reading_minutes FROM v_daily_summary "
                "WHERE date >= '2026-11-10' AND date <= '2026-11-14' ORDER BY date"
            )
        ).scalars().all()
        m_two = sess.execute(
            text(
                "SELECT commits FROM v_daily_summary "
                "WHERE date >= '2026-11-15' AND date <= '2026-11-17' ORDER BY date"
            )
        ).scalars().all()

    return {
        "sql_1": [f"{round(avg_sleep_commit, 1)}"],
        "sql_2": [max_steps_row[0].isoformat(), str(max_steps_row[1])],
        "sql_3": [str(corr_val), f"{round(corr_val, 2)}"],
        "sql_4": [str(streak_val)],
        "sql_5": [str(float(hrv_row[0])), str(float(hrv_row[1]))],
        "search_1": ["sleep", "slept", "exhausted", "2026-09-20", "2026-10-05"],
        "search_2": ["Designing Data-Intensive Applications", "reliability", "scale", "data"],
        "search_3": ["index", "postgresql", "plan", "pgvector"],
        "metrics_1": [str(float(m1[0])), str(int(m1[1]))],
        "metrics_2": [str(int(m2[0])), str(int(m2[1]))],
        "metrics_3": [str(int(v)) for v in m3_rows if int(v) > 0] or ["0"],
        "two_1": [str(int(v)) for v in m_two],
        "two_2": [f"{round(avg_sleep_commit, 1)}", "sleep"],
        "none_1": ["sql_query", "search_notes", "get_metrics", "tools", "help", "data"],
        "none_2": [
            "health", "sleep", "commit", "git", "reading", "book", "screen", "note", "metric"
        ],
    }


def _check_answer_matches(
    category: str,
    answer: str,
    expected_tokens: list[str],
    steps_tools: list[str],
    qid: str = "",
) -> bool:
    ans_lower = answer.lower()
    ans_clean = ans_lower.replace(",", "")
    if category in ("search_notes", "none") or qid in ("B02", "B03"):
        return any(tok.lower() in ans_clean for tok in expected_tokens)
    return all(tok.lower() in ans_clean for tok in expected_tokens)


def main() -> None:
    print(f"Setting up life_test DB (SEED_END={SEED_END.isoformat()})...")
    _setup_bench_db()
    settings = get_settings()
    settings.reference_date = SEED_END

    try:
        exp = _compute_expected_values()
        suite: list[dict[str, Any]] = [
            {
                "id": "B01",
                "cat": "sql_query",
                "exp_tools": ["sql_query"],
                "q": "What was my average sleep on days I pushed code?",
                "tokens": exp["sql_1"],
            },
            {
                "id": "B02",
                "cat": "sql_query",
                "exp_tools": ["sql_query"],
                "q": "Which day had the highest step count?",
                "tokens": exp["sql_2"],
            },
            {
                "id": "B03",
                "cat": "sql_query",
                "exp_tools": ["sql_query"],
                "q": "What is the correlation between sleep hours and commits?",
                "tokens": exp["sql_3"],
            },
            {
                "id": "B04",
                "cat": "sql_query",
                "exp_tools": ["sql_query"],
                "q": "What is my longest streak of consecutive commit days?",
                "tokens": exp["sql_4"],
            },
            {
                "id": "B05",
                "cat": "sql_query",
                "exp_tools": ["sql_query"],
                "q": "What is my average HRV on commit days compared to days with 0 commits?",
                "tokens": exp["sql_5"],
            },
            {
                "id": "B06",
                "cat": "search_notes",
                "exp_tools": ["search_notes"],
                "q": "Search my journal notes for days I slept badly and felt exhausted.",
                "tokens": exp["search_1"],
            },
            {
                "id": "B07",
                "cat": "search_notes",
                "exp_tools": ["search_notes"],
                "q": "Search my reading notes for Designing Data-Intensive Applications.",
                "tokens": exp["search_2"],
            },
            {
                "id": "B08",
                "cat": "search_notes",
                "exp_tools": ["search_notes"],
                "q": "Find notes where I wrote about PostgreSQL query plans or indexing.",
                "tokens": exp["search_3"],
            },
            {
                "id": "B09",
                "cat": "get_metrics",
                "exp_tools": ["get_metrics"],
                "q": "Show my daily sleep_hours and commits from 2026-11-01 to 2026-11-05.",
                "tokens": exp["metrics_1"],
            },
            {
                "id": "B10",
                "cat": "get_metrics",
                "exp_tools": ["get_metrics"],
                "q": "Get my daily steps and screen_minutes between 2026-11-20 and 2026-11-23.",
                "tokens": exp["metrics_2"],
            },
            {
                "id": "B11",
                "cat": "get_metrics",
                "exp_tools": ["get_metrics"],
                "q": "Retrieve my daily reading_minutes from 2026-11-10 to 2026-11-14.",
                "tokens": exp["metrics_3"],
            },
            {
                "id": "B12",
                "cat": "two_tools",
                "exp_tools": ["get_metrics", "search_notes"],
                "q": (
                    "What were my daily commits from 2026-11-15 to 2026-11-17, and what "
                    "engineering topics did my notes mention?"
                ),
                "tokens": exp["two_1"],
            },
            {
                "id": "B13",
                "cat": "two_tools",
                "exp_tools": ["sql_query", "search_notes"],
                "q": (
                    "What was my average sleep when I pushed code, and what do my journal "
                    "entries say about days I slept badly?"
                ),
                "tokens": exp["two_2"],
            },
            {
                "id": "B14",
                "cat": "none",
                "exp_tools": [],
                "q": "Hello! What tools do you have to help me?",
                "tokens": exp["none_1"],
            },
            {
                "id": "B15",
                "cat": "none",
                "exp_tools": [],
                "q": "Without querying the database, what kinds of personal logs do you track?",
                "tokens": exp["none_2"],
            },
        ]

        cat_stats: dict[str, dict[str, Any]] = {}
        all_latencies: list[float] = []
        total_tool_match = 0
        total_correct = 0

        print(f"\n=== REACT AGENT BENCHMARK (count={len(suite)}, model={settings.llm_model}) ===\n")
        for item in suite:
            clear_sessions()
            t0 = time.perf_counter()
            resp = run_react_agent(item["q"], settings=settings)
            lat_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(lat_ms)

            used_tools = [s.action for s in resp.steps if s.action != "final"]
            exp_tools = item["exp_tools"]
            if not exp_tools:
                tool_ok = len(used_tools) == 0
            else:
                tool_ok = all(t in used_tools for t in exp_tools)

            correct = _check_answer_matches(
                item["cat"], resp.answer, item["tokens"], used_tools, qid=item["id"]
            )
            if tool_ok:
                total_tool_match += 1
            if correct:
                total_correct += 1

            st = cat_stats.setdefault(
                item["cat"], {"total": 0, "tool_ok": 0, "correct": 0, "lat": []}
            )
            st["total"] += 1
            if tool_ok:
                st["tool_ok"] += 1
            if correct:
                st["correct"] += 1
            st["lat"].append(lat_ms)

            print(f"{item['id']} [{item['cat']}]: {item['q']}")
            print(f"  Tools Used    : {used_tools} (expected={exp_tools}, tool_match={tool_ok})")
            print(f"  Answer        : {resp.answer}")
            print(f"  Correct       : {correct} (expected_tokens={item['tokens']})")
            print(f"  Latency       : {lat_ms:.0f} ms\n")

        print("=== TOOL-SELECTION BASELINE TABLE ===")
        print("| Category | Count | Tool Match | Answer Correct | Mean Latency (ms) |")
        print("|---|---:|---:|---:|---:|")
        for cat_name in ("sql_query", "search_notes", "get_metrics", "two_tools", "none"):
            st = cat_stats.get(cat_name, {"total": 0, "tool_ok": 0, "correct": 0, "lat": []})
            mean_c = statistics.mean(st["lat"]) if st["lat"] else 0.0
            print(
                f"| `{cat_name}` | {st['total']} | {st['tool_ok']}/{st['total']} | "
                f"{st['correct']}/{st['total']} | {mean_c:.0f} |"
            )

        mean_all = statistics.mean(all_latencies) if all_latencies else 0.0
        max_all = max(all_latencies) if all_latencies else 0.0
        print("\n=== AGENT BENCHMARK TOTALS ===")
        print(f"Model                  : {settings.llm_model}")
        print(f"Tool Selection Match   : {total_tool_match}/{len(suite)}")
        print(f"Answer Accuracy        : {total_correct}/{len(suite)}")
        print(
            f"Latency (mean / max / total): "
            f"{mean_all:.0f} ms / {max_all:.0f} ms / {sum(all_latencies) / 1000.0:.2f}s"
        )
    finally:
        clear_sessions()
        _cleanup_bench_db()


if __name__ == "__main__":
    main()
