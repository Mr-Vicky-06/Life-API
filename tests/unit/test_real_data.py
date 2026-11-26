"""Unit tests for real open-dataset parsers, alignment, and safety guards."""
from __future__ import annotations

import datetime
import json
import pathlib

import pytest

from app.ingestion.real_data import (
    build_health_timeline,
    build_journal_notes,
    build_reading_and_notes,
    build_screen_time_rows,
    collect_github_commits,
    parse_fitbit_csvs,
    parse_goodreads_books,
    parse_grouphealth_csv,
    parse_screentime_social_csv,
    parse_vad_journals,
)
from scripts.ingest_real_data import ingest_real_database


def test_parse_grouphealth_and_fitbit_and_timeline() -> None:
    sleep_json = json.dumps(
        {
            "duration": 420,
            "sleep_deep_duration": 84,
            "sleep_light_duration": 270,
            "sleep_rem_duration": 66,
            "sleep_awake_duration": 10,
        }
    )
    escaped_sleep = sleep_json.replace('"', '""')
    gh_csv = (
        "idx,Uid,Sid,Key,Time,Value,UpdateTime,screentime,expected_sleep,sleep_rating\n"
        f'0,1,s1,sleep,1740191640,"{escaped_sleep}",,0 days 06:30:00,,0.82\n'
        '1,1,s1,steps,1740191640,"{""steps"":9250}",,,,\n'
        '2,1,s1,resting_heart_rate,1740191640,"{""bpm"":58}",,,,\n'
        '3,1,s1,stress,1740191640,"{""stress"":25}",,,,\n'
    )
    gh_recs = parse_grouphealth_csv(gh_csv, uid_order=("1",))
    assert len(gh_recs) == 1
    assert gh_recs[0].sleep_hours == pytest.approx(7.0)
    assert gh_recs[0].sleep_score == 82
    assert gh_recs[0].deep_sleep_min == 84
    assert gh_recs[0].resting_hr == 58
    assert gh_recs[0].steps == 9250
    assert gh_recs[0].screen_total_min == 390
    assert gh_recs[0].source == "zenodo_15171250"

    act_csv = (
        "source,participant-id,timestamp,total-steps\n"
        "fitbit,8378563200,1460419200.0,10450\n"
    )
    slp_csv = (
        "source,participant-id,timestamp,total-sleep-records,"
        "total-minutes-asleep,total-time-in-bed\n"
        "fitbit,8378563200,1460419200.0,1,390,420\n"
    )
    fit_recs = parse_fitbit_csvs(act_csv, slp_csv)
    assert len(fit_recs) == 1
    assert fit_recs[0].sleep_hours == pytest.approx(6.5)
    assert fit_recs[0].steps == 10450
    assert fit_recs[0].source == "fitbit_fitabase"

    end_d = datetime.date(2026, 11, 26)
    timeline = build_health_timeline(gh_recs, fit_recs, end_date=end_d, total_days=2)
    assert [r["date"] for r in timeline] == [datetime.date(2026, 11, 25), end_d]
    assert timeline[0]["source"] == "fitbit_fitabase"
    assert timeline[1]["source"] == "zenodo_15171250"


def test_screen_time_goodreads_and_vad_parsers() -> None:
    sc_csv = (
        "Date,Usage,Notifications,Times opened,App\n"
        "08/26/2022,40,10,5,Instagram\n"
        "08/26/2022,35,20,8,Whatsapp\n"
    )
    social = parse_screentime_social_csv(sc_csv)
    assert social == [75]

    timeline = [
        {
            "date": datetime.date(2026, 11, 25),
            "sleep_hours": 5.8,
            "steps": 6200,
            "_screen_total_min": 300,
        },
        {
            "date": datetime.date(2026, 11, 26),
            "sleep_hours": 8.0,
            "steps": 9500,
            "_screen_total_min": None,
        },
    ]
    screen_rows = build_screen_time_rows(
        timeline, social, commit_counts_by_date={datetime.date(2026, 11, 25): 4}
    )
    day1_sum = sum(r["minutes"] for r in screen_rows if r["date"] == datetime.date(2026, 11, 25))
    assert day1_sum == 300

    gr_csv = (
        "Book Id,Title,Author,Number of Pages,Date Read,My Review\n"
        '1,Designing Data-Intensive Applications,Martin Kleppmann,616,2024/06/07,'
        '"Dense &amp; insightful.<br/><br/>Must read."\n'
        "2,Zero Page Book,Test,0,2024/06/08,skip\n"
    )
    books = parse_goodreads_books(gr_csv)
    assert len(books) == 1
    assert books[0]["review"] == "Dense & insightful. Must read."
    r_rows, r_notes = build_reading_and_notes(
        books, start_date=datetime.date(2026, 11, 25), end_date=datetime.date(2026, 11, 26)
    )
    assert len(r_rows) == 1 and r_rows[0]["pages_read"] == 616
    assert len(r_notes) == 1 and "<br" not in r_notes[0]["content"]

    vad_csv = (
        "Post,V,A,D\n"
        '"I slept badly and felt completely exhausted through my afternoon engineering meetings '
        'while debugging query Latency issues across local services.",-0.45,-0.2,-0.1\n'
        '"I felt great focus today after morning walk and solid progress reading technical '
        'architecture chapters and wrapping tests cleanly.",0.65,0.2,0.4\n'
    )
    low, mid, high = parse_vad_journals(vad_csv)
    assert len(low) == 1 and len(high) == 1 and mid == []
    j_notes = build_journal_notes(timeline, low, mid, high)
    assert len(j_notes) == 1
    assert "slept badly" in j_notes[0]["content"].lower()


def test_local_git_commit_collection_and_reset_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits, commit_notes = collect_github_commits(
        since_date=datetime.date(2026, 11, 20),
        local_repo_root=pathlib.Path("."),
        include_remote=False,
    )
    assert len(commits) >= 1
    assert all(len(c["sha"]) == 40 for c in commits)
    assert len(commit_notes) >= 1

    from types import SimpleNamespace

    monkeypatch.setattr(
        "scripts.ingest_real_data.get_settings",
        lambda: SimpleNamespace(app_env="prod"),
    )
    with pytest.raises(RuntimeError, match="APP_ENV"):
        ingest_real_database(reset=True)
