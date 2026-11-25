"""Held-out 12-question Text-to-SQL benchmark (never embedded in schema_prompt.py)."""
from __future__ import annotations

import datetime
import statistics
from collections import Counter, defaultdict
from typing import Any

from scripts.seed import generate_seed_data

SEED_END = datetime.date(2026, 11, 23)


def compute_heldout_expected() -> dict[int, list[list[Any]]]:
    """Independently compute expected results in pure Python on the deterministic seed data."""
    data = generate_seed_data(end_date=SEED_END)
    health_by_date = {r["date"]: r for r in data["health"]}

    commits_by_date: dict[datetime.date, int] = defaultdict(int)
    additions_by_date: dict[datetime.date, int] = defaultdict(int)
    repo_counts: Counter[str] = Counter()
    for c in data["commits"]:
        commits_by_date[c["commit_date"]] += 1
        additions_by_date[c["commit_date"]] += c["additions"]
        repo_counts[c["repo"]] += 1

    # H01: Weekday vs weekend average sleep_hours (PostgreSQL DOW 1..5 vs 0,6)
    wd_sleep = [r["sleep_hours"] for r in data["health"] if r["date"].weekday() < 5]
    we_sleep = [r["sleep_hours"] for r in data["health"] if r["date"].weekday() >= 5]
    exp_1 = [[round(sum(wd_sleep) / len(wd_sleep), 2), round(sum(we_sleep) / len(we_sleep), 2)]]

    # H02: Median daily steps
    exp_2 = [[round(float(statistics.median(r["steps"] for r in data["health"])), 2)]]

    # H03: Count of zero-commit days
    exp_3 = [[sum(1 for d in health_by_date if commits_by_date[d] == 0)]]

    # H04: Total lines_added between 2026-10-01 and 2026-10-31 inclusive
    oct_lines = sum(
        additions_by_date[d]
        for d in health_by_date
        if datetime.date(2026, 10, 1) <= d <= datetime.date(2026, 10, 31)
    )
    exp_4 = [[oct_lines]]

    # H05: Longest consecutive streak of days with steps >= 8000
    step_dates = sorted(r["date"] for r in data["health"] if r["steps"] >= 8000)
    best = cur = 0
    prev = None
    for d in step_dates:
        cur = (cur + 1) if (prev is not None and (d - prev).days == 1) else 1
        best = max(best, cur)
        prev = d
    exp_5 = [[best]]

    # H06: Average sleep_hours by month
    by_month: dict[datetime.date, list[float]] = defaultdict(list)
    for r in data["health"]:
        month_start = r["date"].replace(day=1)
        by_month[month_start].append(r["sleep_hours"])
    exp_6 = [
        [m.isoformat(), round(sum(vals) / len(vals), 2)]
        for m, vals in sorted(by_month.items())
    ]

    # H07: Top screen-time category on days with sleep_hours < 6
    low_sleep_cats: Counter[str] = Counter()
    for s in data["screen"]:
        if health_by_date[s["date"]]["sleep_hours"] < 6.0:
            low_sleep_cats[s["category"]] += s["minutes"]
    top_cat, top_min = max(low_sleep_cats.items(), key=lambda kv: kv[1])
    exp_7 = [[top_cat, top_min]]

    # H08: Percentage of days with sleep_hours >= 7.5
    good_sleep_days = sum(1 for r in data["health"] if r["sleep_hours"] >= 7.5)
    exp_8 = [[round(100.0 * good_sleep_days / len(data["health"]), 2)]]

    # H09: Commit count per repository (deterministic tie-break by repo ASC)
    exp_9 = [
        [repo, cnt]
        for repo, cnt in sorted(repo_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # H10: Book title with the most total pages read
    book_pages: Counter[str] = Counter()
    for r in data["reading"]:
        book_pages[r["title"]] += r["pages_read"]
    top_book, top_pages = max(book_pages.items(), key=lambda kv: kv[1])
    exp_10 = [[top_book, top_pages]]

    # H11: Day with lowest resting_hr (tie-broken by earliest date)
    min_hr_row = min(data["health"], key=lambda r: (r["resting_hr"], r["date"]))
    exp_11 = [[min_hr_row["date"].isoformat(), min_hr_row["resting_hr"]]]

    # H12: Total commits in the last 14 days (A.3 convention: date > ref - 14 AND date <= ref)
    cutoff_14 = SEED_END - datetime.timedelta(days=14)
    exp_12 = [[sum(commits_by_date[d] for d in health_by_date if cutoff_14 < d <= SEED_END)]]

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
        11: exp_11,
        12: exp_12,
    }


HELDOUT_CASES: list[tuple[int, str, str]] = [
    (
        1,
        "How does average sleep_hours compare on weekdays versus weekends?",
        (
            "SELECT "
            "round(avg(sleep_hours) FILTER "
            "(WHERE extract(dow FROM date) BETWEEN 1 AND 5)::numeric, 2) AS weekday_avg_sleep, "
            "round(avg(sleep_hours) FILTER (WHERE extract(dow FROM date) IN (0, 6))::numeric, 2) "
            "AS weekend_avg_sleep "
            "FROM v_daily_summary"
        ),
    ),
    (
        2,
        "What is the median daily steps across all days?",
        "SELECT round((percentile_cont(0.5) WITHIN GROUP (ORDER BY steps))::numeric, 2) "
        "AS median_steps FROM v_daily_summary",
    ),
    (
        3,
        "How many days had zero commits?",
        "SELECT count(*) AS zero_commit_days FROM v_daily_summary WHERE commits = 0",
    ),
    (
        4,
        "What is the total lines_added between 2026-10-01 and 2026-10-31?",
        "SELECT coalesce(sum(lines_added), 0) AS total_lines_added "
        "FROM v_daily_summary WHERE date BETWEEN DATE '2026-10-01' AND DATE '2026-10-31'",
    ),
    (
        5,
        "What is my longest streak of consecutive days with steps >= 8000?",
        (
            "WITH step_days AS ("
            "SELECT date, date - (row_number() OVER (ORDER BY date))::int AS grp "
            "FROM v_daily_summary WHERE steps >= 8000"
            "), streaks AS ("
            "SELECT count(*) AS streak_len FROM step_days GROUP BY grp"
            ") SELECT coalesce(max(streak_len), 0) AS longest_streak FROM streaks"
        ),
    ),
    (
        6,
        "What is my average sleep_hours grouped by month?",
        "SELECT date_trunc('month', date)::date AS month, "
        "round(avg(sleep_hours)::numeric, 2) AS avg_sleep "
        "FROM v_daily_summary GROUP BY 1 ORDER BY 1",
    ),
    (
        7,
        "Which screen time category has the most total minutes on days with sleep_hours < 6?",
        "SELECT s.category, sum(s.minutes) AS total_minutes "
        "FROM v_screen_time s JOIN v_daily_summary d ON s.date = d.date "
        "WHERE d.sleep_hours < 6 GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    ),
    (
        8,
        "What percentage of days had sleep_hours >= 7.5?",
        "SELECT round(100.0 * count(*) FILTER (WHERE sleep_hours >= 7.5)::numeric / count(*), 2) "
        "AS pct_good_sleep FROM v_daily_summary",
    ),
    (
        9,
        "How many commits were pushed to each repository?",
        "SELECT repo, count(*) AS commit_count FROM v_commits GROUP BY 1 ORDER BY 2 DESC, 1 ASC",
    ),
    (
        10,
        "Which book had the most total pages read?",
        "SELECT title, sum(pages_read) AS total_pages "
        "FROM v_reading GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    ),
    (
        11,
        "Which day had the lowest resting_hr?",
        "SELECT date, resting_hr FROM v_daily_summary "
        "WHERE resting_hr IS NOT NULL ORDER BY resting_hr ASC, date ASC LIMIT 1",
    ),
    (
        12,
        "How many commits did I push in the last 14 days?",
        "SELECT coalesce(sum(commits), 0) AS commits_last_14d FROM v_daily_summary "
        "WHERE date > DATE '2026-11-23' - 14 AND date <= DATE '2026-11-23'",
    ),
]
