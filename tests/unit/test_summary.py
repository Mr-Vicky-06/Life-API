"""Tests for safer summaries (E.1 template, E.2 number verification), stage logs, and prompt."""
from __future__ import annotations

import datetime
import logging
from types import SimpleNamespace

import pytest

from app.api.routes_query import (
    build_template_summary,
    summarize_results,
    verify_summary_numbers,
)
from app.config import Settings
from app.sql_agent.executor import SQLExecutionResult
from app.sql_agent.schema_prompt import build_schema_prompt, get_reference_date


def _dummy_settings() -> Settings:
    return Settings(
        app_env="dev",
        app_api_key="test-key",
        database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life_test",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life_test",
    )


def test_single_row_and_small_results_use_deterministic_template_without_llm(
    monkeypatch: pytest.MonkeyPatch,
):
    """E.1: empty, 1 row w/ <=3 cols, and <5 cells never invoke LLM."""
    llm_calls = 0

    def fail_if_called(**kwargs):
        nonlocal llm_calls
        llm_calls += 1
        raise AssertionError("LLM must not be called for deterministic template summaries")

    monkeypatch.setattr("app.gateway.llm.litellm.completion", fail_if_called)
    cfg = _dummy_settings()

    # Empty
    s0 = summarize_results(
        "Any commits?", "SELECT 1", SQLExecutionResult(["commits"], [], 0), settings=cfg
    )
    assert "No matching records" in s0

    # 1 row, 1 col
    s1 = summarize_results(
        "Avg sleep?",
        "SELECT avg(sleep_hours)",
        SQLExecutionResult(["avg_sleep"], [[7.44]], 1),
        settings=cfg,
    )
    assert "7.44" in s1

    # 1 row, 3 cols
    s2 = summarize_results(
        "Summary?",
        "SELECT 1",
        SQLExecutionResult(["date", "steps", "commits"], [["2026-09-26", 14760, 5]], 1),
        settings=cfg,
    )
    assert "2026-09-26" in s2 and "14760" in s2 and "5" in s2

    # 2 rows x 2 cols = 4 cells (< 5 cells)
    s3 = summarize_results(
        "Two rows?",
        "SELECT 1",
        SQLExecutionResult(["repo", "commits"], [["repoA", 200], ["repoB", 198]], 2),
        settings=cfg,
    )
    assert "200" in s3 and "198" in s3
    assert llm_calls == 0


def test_multi_row_llm_summary_accepted_when_all_numbers_in_rows(monkeypatch: pytest.MonkeyPatch):
    """E.2: >= 5 cells uses LLM summary and accepts when numbers match rows (incl. rounding)."""
    rows = [
        ["2026-08-24", 17.4],
        ["2026-08-31", 42.0],
        ["2026-09-07", 21.0],
    ]
    exec_res = SQLExecutionResult(["week", "commits"], rows, len(rows))

    def fake_completion(**kwargs):
        content = (
            "Weekly commits started at 17 on 2026-08-24, peaked at 42 on 2026-08-31, "
            "and settled at 21 on 2026-09-07."
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(completion_tokens=22),
        )

    monkeypatch.setattr("app.gateway.llm.litellm.completion", fake_completion)
    summary = summarize_results(
        "Weekly commits?", "SELECT ...", exec_res, settings=_dummy_settings()
    )
    assert "Weekly commits started at 17" in summary


def test_multi_row_llm_summary_falls_back_when_stub_invents_number(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """E.2: if stub LLM invents a number not in rows, fall back to value-listing template."""
    rows = [
        ["Productivity", 21324],
        ["Entertainment", 7266],
        ["Social", 5272],
    ]
    exec_res = SQLExecutionResult(["category", "total"], rows, len(rows))

    def hallucinating_completion(**kwargs):
        # 99999 is fabricated and not present in rows!
        content = "Your top category was Productivity with 99999 minutes across 3 categories."
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(completion_tokens=18),
        )

    monkeypatch.setattr("app.gateway.llm.litellm.completion", hallucinating_completion)
    with caplog.at_level(logging.WARNING):
        summary = summarize_results(
            "Top categories?", "SELECT ...", exec_res, settings=_dummy_settings()
        )

    assert "99999" not in summary
    expected_template = build_template_summary(exec_res)
    assert summary == expected_template
    assert "21324" in summary and "7266" in summary and "5272" in summary
    assert any("falling back to template" in r.message for r in caplog.records)


def test_verify_summary_numbers_handles_comma_formatting_and_dates():
    rows = [["2026-09-26", 14760.45], ["2026-09-27", 8000.0], ["2026-09-28", 9200.12]]
    assert verify_summary_numbers("Peak was 14,760.5 on 2026-09-26.", rows) is True
    assert verify_summary_numbers("Peak was 14,760 on 2026-12-31.", rows) is False
    assert verify_summary_numbers("Peak was 15,000 on 2026-09-26.", rows) is False


def test_schema_prompt_uses_reference_date_and_states_last_n_days_convention():
    """A.2 & A.3: REFERENCE_DATE overrides prompt today and documents `date > ref - N`."""
    cfg = _dummy_settings()
    cfg.reference_date = datetime.date(2026, 11, 23)
    assert get_reference_date(cfg) == datetime.date(2026, 11, 23)

    prompt = build_schema_prompt(settings=cfg)
    assert "2026-11-23" in prompt
    assert "date > DATE '2026-11-23' - N AND date <= DATE '2026-11-23'" in prompt
    # Generic patterns (B) present without copying heldout questions
    assert "percentile_cont(0.5)" in prompt
    assert "FILTER (WHERE" in prompt
    assert "row_number() OVER (ORDER BY date)" in prompt
    assert "ORDER BY col DESC/ASC LIMIT 1" in prompt
