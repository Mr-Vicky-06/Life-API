"""Benchmark (NOT a pytest gate): evaluate real llama3.1:8b on the 10 golden SQL questions."""
from __future__ import annotations

import datetime
import time
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import reset_engines, ro_engine
from app.gateway.guardrails import check_input
from app.sql_agent.executor import execute_readonly_sql
from app.sql_agent.generator import generate_sql, repair_sql
from app.sql_agent.schema_prompt import build_schema_prompt
from app.sql_agent.validator import validate_sql
from scripts.seed import seed_database
from tests.golden.test_golden_sql import SEED_END, compute_golden_expected

BENCH_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
BENCH_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{BENCH_DB_NAME}"
BENCH_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{BENCH_DB_NAME}"

# Q1, Q4, Q6, Q8 directly overlap with the 5 few-shot examples in DATA_AND_RAG.md §7.
FEW_SHOT_OVERLAP_IDS = {1, 4, 6, 8}

GOLDEN_QUESTIONS: list[tuple[int, str]] = [
    (1, "What was my average sleep on days with commits > 0?"),
    (2, "What were my total commits in the last 30 days?"),
    (3, "Which day had the most steps?"),
    (4, "What is the correlation between sleep_hours and commits?"),
    (5, "What is my average screen minutes on days sleep < 6?"),
    (6, "What are my weekly commit totals?"),
    (7, "How many total pages did I read in the last 14 days?"),
    (8, "What are my top 3 screen-time categories?"),
    (9, "What is my average HRV on days with >=1 commit compared to days with 0 commits?"),
    (10, "What is my longest streak of consecutive commit days?"),
]


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
    reset_engines()
    seed_database(end_date=SEED_END)


def _cleanup_bench_db() -> None:
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {BENCH_DB_NAME} WITH (FORCE);")


def _normalize_scalar(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3)
    return v


def _results_equal(actual_rows: list[list[Any]], expected_rows: list[list[Any]]) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False
    for a_row, e_row in zip(actual_rows, expected_rows, strict=True):
        if len(a_row) != len(e_row):
            return False
        for av, ev in zip(a_row, e_row, strict=True):
            an, en = _normalize_scalar(av), _normalize_scalar(ev)
            if isinstance(an, (int, float)) and isinstance(en, (int, float)):
                if abs(float(an) - float(en)) > 0.05:
                    return False
            elif str(an) != str(en):
                return False
    return True


def main() -> None:
    print("Preparing isolated life_test database with fixed SEED_END_DATE=2026-11-23...")
    _setup_bench_db()
    settings = get_settings()
    expected_map = compute_golden_expected()
    schema_prompt = build_schema_prompt(settings=settings)

    executed_ok_count = 0
    matched_count = 0
    overlap_matched = 0
    non_overlap_matched = 0
    total_latency_ms = 0.0

    print("\n=== REAL LLM TEXT-TO-SQL BENCHMARK (10 GOLDEN QUESTIONS) ===")
    print(
        f"Model: {settings.llm_model} | Schema prompt ref date: {datetime.date.today().isoformat()}"
    )
    print(
        "Note: Questions Q1, Q4, Q6, Q8 overlap with few-shot examples in "
        "schema_prompt.py (overstate accuracy).\n"
    )

    try:
        for qid, question in GOLDEN_QUESTIONS:
            overlap_tag = "[FEW-SHOT OVERLAP]" if qid in FEW_SHOT_OVERLAP_IDS else "[NOVEL]"
            t0 = time.perf_counter()
            gen_sql = ""
            exec_ok = False
            matched = False
            err_detail = ""
            actual_rows: list[list[Any]] = []

            try:
                check_input(question)
                generated = generate_sql(question, settings=settings, system_prompt=schema_prompt)
                gen_sql = validate_sql(generated.sql)
                with Session(bind=ro_engine()) as ro_sess:
                    try:
                        res = execute_readonly_sql(gen_sql, session=ro_sess)
                    except Exception as first_err:
                        repaired = repair_sql(
                            question,
                            gen_sql,
                            str(first_err),
                            settings=settings,
                            system_prompt=schema_prompt,
                        )
                        gen_sql = validate_sql(repaired.sql)
                        res = execute_readonly_sql(gen_sql, session=ro_sess)
                exec_ok = True
                actual_rows = res.rows
                matched = _results_equal(actual_rows, expected_map[qid])
            except Exception as exc:
                err_detail = str(exc).splitlines()[0][:160]

            latency_ms = (time.perf_counter() - t0) * 1000.0
            total_latency_ms += latency_ms
            if exec_ok:
                executed_ok_count += 1
            if matched:
                matched_count += 1
                if qid in FEW_SHOT_OVERLAP_IDS:
                    overlap_matched += 1
                else:
                    non_overlap_matched += 1

            print(f"Q{qid:02d} {overlap_tag}: {question}")
            print(f"  Generated SQL : {gen_sql or '(none)'}")
            print(f"  Executed OK   : {exec_ok}" + (f" ({err_detail})" if err_detail else ""))
            mismatch_info = (
                ""
                if matched
                else f" (actual={actual_rows[:2]} vs expected={expected_map[qid][:2]})"
            )
            print(f"  Result Match  : {matched}{mismatch_info}")
            print(f"  Latency       : {latency_ms:.0f} ms\n")

        print("=== BENCHMARK TOTALS ===")
        print(f"Executed OK                  : {executed_ok_count}/10")
        print(f"Exact/Tolerance Result Match : {matched_count}/10")
        print(f"  Few-shot overlap (Q1,4,6,8): {overlap_matched}/4")
        print(f"  Non-overlap (Q2,3,5,7,9,10): {non_overlap_matched}/6")
        avg_ms = total_latency_ms / 10.0
        print(
            f"Total Latency                : {total_latency_ms / 1000.0:.2f}s "
            f"(avg {avg_ms:.0f} ms/question)"
        )
    finally:
        _cleanup_bench_db()


if __name__ == "__main__":
    main()
