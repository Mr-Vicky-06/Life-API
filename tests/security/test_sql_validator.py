"""Security tests for sqlglot AST SQL validator and schema prompt isolation."""
from __future__ import annotations

import datetime
import re

import pytest

from app.gateway.exceptions import SQLRejected
from app.sql_agent.schema_prompt import build_schema_prompt
from app.sql_agent.validator import validate_sql

REJECTED_QUERIES = [
    ("drop_table", "DROP TABLE notes;"),
    ("multi_statement", "SELECT 1; SELECT 2;"),
    ("pg_sleep", "SELECT pg_sleep(10);"),
    ("base_table_notes", "SELECT * FROM notes;"),
    (
        "insert",
        "INSERT INTO notes (ts, note_date, source_type, content, content_hash) "
        "VALUES (now(), '2026-01-01', 'journal', 'x', 'h');",
    ),
    ("select_into_trailing", "SELECT * FROM v_daily_summary INTO x;"),
    ("select_into_pg", "SELECT * INTO x FROM v_daily_summary;"),
    ("cte_delete", "WITH x AS (DELETE FROM notes RETURNING *) SELECT * FROM x;"),
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd');"),
    ("schema_qualified_public_notes", "SELECT * FROM public.notes;"),
    ("schema_qualified_public_view", "SELECT * FROM public.v_daily_summary;"),
    ("quoted_notes", 'SELECT * FROM "notes";'),
    ("mixed_case_notes", "SELECT * FROM NoTeS;"),
    (
        "subquery_notes",
        "SELECT * FROM v_daily_summary WHERE date IN (SELECT note_date FROM notes);",
    ),
    ("union_notes", "SELECT date FROM v_daily_summary UNION SELECT note_date FROM notes;"),
    ("information_schema", "SELECT * FROM information_schema.tables;"),
    ("pg_catalog_tables", "SELECT * FROM pg_catalog.pg_tables;"),
    ("current_setting", "SELECT current_setting('x');"),
    ("pg_catalog_func", "SELECT pg_catalog.pg_sleep(1);"),
    ("for_update", "SELECT * FROM v_daily_summary FOR UPDATE;"),
    ("lock_table", "LOCK TABLE v_daily_summary IN ACCESS EXCLUSIVE MODE;"),
    ("comment_semicolon", "SELECT * FROM v_daily_summary /* ; */;"),
    ("comment_into", "SELECT * FROM v_daily_summary -- INTO x"),
    ("comment_for_update", "SELECT * FROM v_daily_summary /* FOR UPDATE */"),
    ("comment_lock", "SELECT * FROM v_daily_summary -- LOCK"),
    (
        "blocked_set_config",
        "SELECT set_config('log_statement', 'all', false) FROM v_daily_summary;",
    ),
    ("blocked_lo_import", "SELECT lo_import('/etc/passwd') FROM v_daily_summary;"),
    ("blocked_pg_ls_dir", "SELECT pg_ls_dir('.') FROM v_daily_summary;"),
    ("empty", ""),
    ("whitespace", "   "),
]


@pytest.mark.parametrize(("name", "sql"), REJECTED_QUERIES, ids=[x[0] for x in REJECTED_QUERIES])
def test_sql_validator_rejects_unsafe_or_disallowed_queries(name: str, sql: str):
    """Disallowed statement, table, function, comment, or schema raises SQLRejected."""
    with pytest.raises(SQLRejected) as exc_info:
        validate_sql(sql)
    assert exc_info.value.code == "sql_rejected"
    assert exc_info.value.status_code == 422


def test_sql_validator_adds_default_limit_200():
    """Plain allowlisted SELECT receives LIMIT 200 when missing."""
    normalized = validate_sql("SELECT avg(sleep_hours) FROM v_daily_summary")
    assert "LIMIT 200" in normalized.upper()
    assert "V_DAILY_SUMMARY" in normalized.upper()


def test_sql_validator_clamps_large_limit_to_200():
    """LIMIT > 200 and FETCH FIRST > 200 are clamped down to LIMIT 200."""
    clamped = validate_sql("SELECT * FROM v_daily_summary LIMIT 1000")
    assert "LIMIT 200" in clamped.upper()
    assert "1000" not in clamped

    clamped_fetch = validate_sql("SELECT * FROM v_reading FETCH FIRST 500 ROWS ONLY")
    assert "LIMIT 200" in clamped_fetch.upper()
    assert "500" not in clamped_fetch


def test_sql_validator_preserves_smaller_limit_and_allows_ctes():
    """Valid CTEs and limits <= 200 are preserved cleanly."""
    small = validate_sql("SELECT category, minutes FROM v_screen_time LIMIT 5;")
    assert "LIMIT 5" in small.upper()

    cte = validate_sql(
        "WITH daily AS (SELECT date, sleep_hours FROM v_daily_summary WHERE commits > 0) "
        "SELECT avg(sleep_hours) FROM daily"
    )
    assert "LIMIT 200" in cte.upper()
    assert "DAILY" in cte.upper()


def test_schema_prompt_never_mentions_base_tables():
    """Schema prompt exposes only the 4 allowlisted views and zero base table names."""
    prompt = build_schema_prompt(today=datetime.date(2026, 11, 23))
    for view in ("v_daily_summary", "v_commits", "v_screen_time", "v_reading"):
        assert view in prompt

    forbidden_base_tables = (
        "health_daily",
        "github_commits",
        "reading_log",
        "screen_time",
        "notes",
        "note_chunks",
        "query_log",
    )
    for tbl in forbidden_base_tables:
        assert not re.search(rf"\b{tbl}\b", prompt), f"Base table '{tbl}' leaked in schema prompt"
