"""Database seed script for 90-day synthetic dataset with pgvector embeddings."""
from __future__ import annotations

import datetime
import hashlib
import random
from typing import Any

from sqlalchemy.orm import Session

from app.db import get_rw_engine
from app.ingestion.loaders import (
    upsert_github_commits,
    upsert_health_daily,
    upsert_notes,
    upsert_reading_log,
    upsert_screen_time,
)

# Realistic books for reading log and reading notes
BOOKS = [
    (
        "Designing Data-Intensive Applications",
        "Reliability, scalability, and maintainability are fundamental data concerns.",
    ),
    (
        "Atomic Habits",
        "Small changes in daily habits compound over time into remarkable results.",
    ),
    (
        "Deep Work",
        "The ability to perform deep work is becoming rare and valuable.",
    ),
    (
        "Fluent Python",
        "Python's data model provides an elegant interface for objects.",
    ),
    (
        "Clean Code",
        "Writing clean code requires continuous discipline and small functions.",
    ),
]

JOURNAL_PROMPTS = [
    "Reflected on system architecture and async pipeline throughput today.",
    "Good morning run and solid focus block in the early afternoon.",
    "Had a deep coding session refactoring PostgreSQL query plans and indexes.",
    "Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher.",
    "Late evening work session. Sleep latency was slightly delayed but productive.",
    "Implemented automated schema migrations and verified read-only security constraints.",
    "Reviewed database indexing strategies with pgvector HNSW and tsvector GIN.",
    "Went for an evening walk to decompress after intensive API debugging.",
    "Focused on building modular, idempotent data ingestion pipelines.",
    "Energy dipped in the mid-afternoon; took a power nap and recovered focus.",
    "Solid commit velocity today; made good progress on data normalization.",
    "Reviewed sleep metrics against commit volume; clear correlation with deep sleep.",
    "Experimented with hybrid search RRF reciprocal rank fusion algorithms.",
    "Organized personal study notes and planned next sprint milestones.",
    "Productive day overall; minimized social screen time and prioritized reading.",
]


def generate_seed_data() -> dict[str, Any]:
    """Generate deterministic 90-day dataset."""
    random.seed(42)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=89)

    health_rows: list[dict[str, Any]] = []
    commit_rows: list[dict[str, Any]] = []
    reading_rows: list[dict[str, Any]] = []
    screen_rows: list[dict[str, Any]] = []
    note_rows: list[dict[str, Any]] = []

    journal_idx = 0
    reading_note_idx = 0

    for day_offset in range(90):
        current_date = start_date + datetime.timedelta(days=day_offset)

        # 1. Health daily: sleep weakly correlated around 7.2h
        sleep_hours = round(random.normalvariate(7.2, 0.9), 2)
        sleep_hours = max(5.0, min(9.5, sleep_hours))
        sleep_score = int(min(100, max(50, int(sleep_hours * 11 + random.randint(-5, 5)))))
        deep_sleep_min = int(min(130, max(30, int(sleep_hours * 11.5 + random.randint(-10, 10)))))
        hrv_val = 50.0 + (sleep_hours - 7.0) * 8 + random.uniform(-5, 5)
        hrv_ms = round(max(30.0, min(85.0, hrv_val)), 2)
        r_hr = 65 - (sleep_hours - 7.0) * 3 + random.randint(-2, 2)
        resting_hr = int(max(48, min(75, r_hr)))
        steps = int(max(3000, min(16000, random.normalvariate(8500, 2200))))

        health_rows.append({
            "date": current_date,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
            "deep_sleep_min": deep_sleep_min,
            "hrv_ms": hrv_ms,
            "resting_hr": resting_hr,
            "steps": steps,
            "source": "csv",
        })

        # 2. Commits: commits ≈ 2 + 3·(sleep−6.5) + noise, min 0
        noise = random.uniform(-1.5, 1.5)
        raw_commits = 2.0 + 3.0 * (sleep_hours - 6.5) + noise
        commit_count = max(0, int(round(raw_commits)))

        for c_idx in range(commit_count):
            sha = hashlib.sha1(f"commit_{current_date}_{c_idx}".encode()).hexdigest()
            repo = random.choice(["Mr-Vicky-06/Life-API", "Mr-Vicky-06/voicecore"])
            committed_at = datetime.datetime.combine(
                current_date,
                datetime.time(hour=9 + (c_idx * 2) % 12, minute=(c_idx * 17) % 60),
                tzinfo=datetime.UTC,
            )
            msg = f"chore(core): commit {c_idx + 1} on {current_date} updating modules"
            commit_rows.append({
                "sha": sha,
                "repo": repo,
                "committed_at": committed_at,
                "commit_date": current_date,
                "message": msg,
                "additions": random.randint(5, 120),
                "deletions": random.randint(1, 40),
            })

        # 3. Reading log: ~70% of days
        if random.random() < 0.72:
            book_title, _ = random.choice(BOOKS)
            reading_rows.append({
                "date": current_date,
                "title": book_title,
                "pages_read": random.randint(12, 45),
                "minutes": random.randint(20, 60),
            })

        # 4. Screen time: 3 categories per day
        screen_rows.append({
            "date": current_date,
            "category": "Productivity",
            "minutes": random.randint(120, 360),
        })
        screen_rows.append({
            "date": current_date,
            "category": "Entertainment",
            "minutes": random.randint(30, 150),
        })
        screen_rows.append({
            "date": current_date,
            "category": "Social",
            "minutes": random.randint(20, 90),
        })

        # 5. Notes: >= 40 journal notes across 90 days (~55% chance per day)
        if random.random() < 0.58 and journal_idx < 50:
            prompt = JOURNAL_PROMPTS[journal_idx % len(JOURNAL_PROMPTS)]
            journal_text = (
                f"Day {day_offset + 1} ({current_date}): {prompt} "
                f"Recorded sleep was {sleep_hours} hours with {steps} steps. "
                "Maintained focus on incremental delivery and rigorous automated test coverage."
            )
            ts = datetime.datetime.combine(
                current_date, datetime.time(21, 30), tzinfo=datetime.UTC
            )
            note_rows.append({
                "ts": ts,
                "note_date": current_date,
                "source_type": "journal",
                "content": journal_text,
            })
            journal_idx += 1

        # Reading notes: >= 20 reading notes across 90 days (~30% chance per day)
        if random.random() < 0.35 and reading_note_idx < 25:
            book_title, insight = BOOKS[reading_note_idx % len(BOOKS)]
            reading_note_text = (
                f"Reading Notes: {book_title}. "
                f"Core Takeaway: {insight} "
                "Reflecting on applying these concepts to personal data systems."
            )
            ts = datetime.datetime.combine(
                current_date, datetime.time(22, 15), tzinfo=datetime.UTC
            )
            note_rows.append({
                "ts": ts,
                "note_date": current_date,
                "source_type": "reading_note",
                "content": reading_note_text,
            })
            reading_note_idx += 1

    return {
        "health": health_rows,
        "commits": commit_rows,
        "reading": reading_rows,
        "screen": screen_rows,
        "notes": note_rows,
    }


def seed_database() -> None:
    """Populate database idempotently with synthetic dataset."""
    engine = get_rw_engine()
    data = generate_seed_data()

    with Session(bind=engine) as session:
        h_res = upsert_health_daily(session, data["health"])
        c_res = upsert_github_commits(session, data["commits"])
        r_res = upsert_reading_log(session, data["reading"])
        s_res = upsert_screen_time(session, data["screen"])
        n_res = upsert_notes(session, data["notes"])
        session.commit()

        print(
            f"Seed completed: health={h_res.inserted}ins/{h_res.updated}upd, "
            f"commits={c_res.inserted}ins/{c_res.updated}upd, "
            f"reading={r_res.inserted}ins/{r_res.updated}upd, "
            f"screen={s_res.inserted}ins/{s_res.updated}upd, "
            f"notes={n_res.inserted}ins/{n_res.skipped}skip"
        )


if __name__ == "__main__":
    seed_database()
