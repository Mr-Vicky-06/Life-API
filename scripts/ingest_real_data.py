"""Ingest verified real open datasets + real GitHub commits for Life-API showcase."""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_rw_engine
from app.ingestion.loaders import (
    upsert_github_commits,
    upsert_health_daily,
    upsert_notes,
    upsert_reading_log,
    upsert_screen_time,
)
from app.ingestion.real_data import (
    DEFAULT_GITHUB_USERNAME,
    FITBIT_ACTIVITY_URL,
    FITBIT_SLEEP_URL,
    GOODREADS_EXPORT_URL,
    JOURNAL_VAD_URL,
    REAL_SOURCES_MANIFEST,
    SCREENTIME_APP_URL,
    ZENODO_GROUPHEALTH_URL,
    build_health_timeline,
    build_journal_notes,
    build_reading_and_notes,
    build_screen_time_rows,
    collect_github_commits,
    download_cached,
    parse_fitbit_csvs,
    parse_goodreads_books,
    parse_grouphealth_csv,
    parse_screentime_social_csv,
    parse_vad_journals,
)
from scripts.seed import _truncate_data_tables


def build_real_dataset(
    *,
    end_date: datetime.date | None = None,
    total_days: int = 179,
    github_username: str | None = None,
    refresh_cache: bool = False,
    include_remote_git: bool = True,
) -> dict[str, Any]:
    """Download/load real datasets and align streams cleanly onto the showcase window."""
    resolved_end = end_date or datetime.date.today()
    start_date = resolved_end - datetime.timedelta(days=total_days - 1)
    user = github_username or get_settings().github_username or DEFAULT_GITHUB_USERNAME

    gh_text = download_cached(
        ZENODO_GROUPHEALTH_URL, "GroupHealth_SleepScreen.csv", refresh=refresh_cache
    )
    fit_act_text = download_cached(
        FITBIT_ACTIVITY_URL, "fitbit_dailyActivity_merged.csv", refresh=refresh_cache
    )
    fit_slp_text = download_cached(
        FITBIT_SLEEP_URL, "fitbit_sleepDay_merged.csv", refresh=refresh_cache
    )
    screen_text = download_cached(
        SCREENTIME_APP_URL, "Screentime-App-Details.csv", refresh=refresh_cache
    )
    goodreads_text = download_cached(
        GOODREADS_EXPORT_URL, "goodreads_library_export.csv", refresh=refresh_cache
    )
    vad_text = download_cached(
        JOURNAL_VAD_URL, "journal_vad_data.csv", refresh=refresh_cache
    )

    gh_records = parse_grouphealth_csv(gh_text)
    fit_records = parse_fitbit_csvs(fit_act_text, fit_slp_text)
    health_timeline = build_health_timeline(
        gh_records, fit_records, end_date=resolved_end, total_days=total_days
    )

    commit_rows, commit_notes = collect_github_commits(
        since_date=start_date,
        username=user,
        include_remote=include_remote_git,
    )
    commit_counts = collections.Counter(c["commit_date"] for c in commit_rows)

    social_series = parse_screentime_social_csv(screen_text)
    screen_rows = build_screen_time_rows(health_timeline, social_series, commit_counts)

    books = parse_goodreads_books(goodreads_text)
    reading_rows, reading_notes = build_reading_and_notes(
        books, start_date=start_date, end_date=resolved_end
    )

    low_sleep, mid_daily, high_pos = parse_vad_journals(vad_text)
    journal_notes = build_journal_notes(health_timeline, low_sleep, mid_daily, high_pos)

    health_clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in health_timeline]
    notes_rows = journal_notes + reading_notes + commit_notes

    return {
        "start_date": start_date,
        "end_date": resolved_end,
        "health": health_clean,
        "commits": commit_rows,
        "reading": reading_rows,
        "screen": screen_rows,
        "notes": notes_rows,
    }


def ingest_real_database(
    *,
    reset: bool = False,
    end_date: datetime.date | None = None,
    days: int = 179,
    github_username: str | None = None,
    refresh_cache: bool = False,
    manifest_out: pathlib.Path | None = pathlib.Path("reports/real-sources-summary.json"),
) -> dict[str, Any]:
    """Populate PostgreSQL idempotently from real open internet datasets & GitHub history."""
    settings = get_settings()
    if reset and settings.app_env.lower() != "dev":
        raise RuntimeError(
            f"Refusing to run --reset when APP_ENV='{settings.app_env}' (requires 'dev')."
        )

    payload = build_real_dataset(
        end_date=end_date,
        total_days=days,
        github_username=github_username,
        refresh_cache=refresh_cache,
    )
    engine = get_rw_engine()
    with Session(bind=engine) as session:
        if reset:
            _truncate_data_tables(session)
        h_res = upsert_health_daily(session, payload["health"])
        c_res = upsert_github_commits(session, payload["commits"])
        r_res = upsert_reading_log(session, payload["reading"])
        s_res = upsert_screen_time(session, payload["screen"])
        n_res = upsert_notes(session, payload["notes"])
        session.commit()

    summary = {
        "window": f"{payload['start_date'].isoformat()}..{payload['end_date'].isoformat()}",
        "health": {"inserted": h_res.inserted, "updated": h_res.updated},
        "commits": {"inserted": c_res.inserted, "updated": c_res.updated},
        "reading": {"inserted": r_res.inserted, "updated": r_res.updated},
        "screen_time": {"inserted": s_res.inserted, "updated": s_res.updated},
        "notes": {"inserted": n_res.inserted, "skipped": n_res.skipped},
        "sources": REAL_SOURCES_MANIFEST,
    }
    if manifest_out is not None:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Real data ingest completed ({summary['window']}): "
        f"health={h_res.inserted}ins/{h_res.updated}upd, "
        f"commits={c_res.inserted}ins/{c_res.updated}upd, "
        f"reading={r_res.inserted}ins/{r_res.updated}upd, "
        f"screen={s_res.inserted}ins/{s_res.updated}upd, "
        f"notes={n_res.inserted}ins/{n_res.skipped}skip"
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest verified real open datasets into Life-API."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate data tables before ingesting real data (requires APP_ENV=dev).",
    )
    parser.add_argument(
        "--end-date",
        type=datetime.date.fromisoformat,
        default=None,
        help="Anchor end date (YYYY-MM-DD, default: today).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=179,
        help="Timeline length in calendar days (default: 179).",
    )
    parser.add_argument(
        "--github-user",
        default=None,
        help="Override GitHub username for public repo commits.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download datasets even if already cached in .cache/real_data.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    ingest_real_database(
        reset=args.reset,
        end_date=args.end_date,
        days=args.days,
        github_username=args.github_user,
        refresh_cache=args.refresh,
    )
