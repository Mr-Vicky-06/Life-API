"""Security and startup config tests for Step 0A seed reset guard & Step 0B API key guard."""
from __future__ import annotations

import datetime
import logging

import pytest
from pydantic import ValidationError

from app.config import Settings
from scripts.seed import generate_seed_data, seed_database


def test_non_dev_refuses_default_api_key():
    """App refuses to configure when APP_ENV != dev and APP_API_KEY is default 'change-me'."""
    with pytest.raises(ValidationError, match="APP_API_KEY must be changed from the default"):
        Settings(
            app_env="prod",
            app_api_key="change-me",
            database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life",
            database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life",
        )


def test_dev_allows_default_key_and_non_dev_allows_custom_key():
    """Dev allows default key; non-dev accepts a custom 32+ char key."""
    s_dev = Settings(
        app_env="dev",
        app_api_key="change-me",
        database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life",
    )
    assert s_dev.app_api_key == "change-me"

    s_prod = Settings(
        app_env="prod",
        app_api_key="a" * 32,
        database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life",
    )
    assert s_prod.app_env == "prod"


def test_seed_reset_refused_in_non_dev(monkeypatch):
    """seed_database(reset=True) refuses to truncate when APP_ENV != 'dev'."""
    fake_settings = Settings(
        app_env="prod",
        app_api_key="x" * 32,
        database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life_test",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life_test",
    )
    monkeypatch.setattr("scripts.seed.get_settings", lambda: fake_settings)
    with pytest.raises(RuntimeError, match="requires 'dev'"):
        seed_database(reset=True)


def test_seed_data_fixed_end_date_and_consistent_journal_text():
    """Seed is deterministic, date-anchored, max 1 journal/date, and text matches sleep metrics."""
    data = generate_seed_data(end_date=datetime.date(2026, 11, 23))
    health_by_date = {r["date"]: r for r in data["health"]}
    assert len(health_by_date) == 90
    assert min(health_by_date) == datetime.date(2026, 8, 26)
    assert max(health_by_date) == datetime.date(2026, 11, 23)

    journals = [n for n in data["notes"] if n["source_type"] == "journal"]
    reading_notes = [n for n in data["notes"] if n["source_type"] == "reading_note"]
    assert len(journals) >= 40
    assert len(reading_notes) >= 20
    assert len({n["note_date"] for n in journals}) == len(journals)

    for note in journals:
        sleep = health_by_date[note["note_date"]]["sleep_hours"]
        content = note["content"]
        assert not content.startswith("Day ")
        if sleep < 6.0:
            assert "Slept badly" in content
            assert "well-rested" not in content
        elif sleep >= 7.5:
            assert "well-rested" in content
            assert "Slept badly" not in content


def test_cloud_llm_enabled_logs_startup_warning(caplog):
    """Enabling cloud_llm_enabled=True logs a startup warning about masked prompts."""
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings(
            app_env="dev",
            app_api_key="change-me",
            database_url="postgresql+psycopg://life:life@127.0.0.1:5432/life",
            database_url_ro="postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/life",
            cloud_llm_enabled=True,
            llm_model="gpt-4o-mini",
        )
    assert any("masked prompts" in rec.getMessage().lower() for rec in caplog.records)
