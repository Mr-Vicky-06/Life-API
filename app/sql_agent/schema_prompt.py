"""Schema prompt builder exposing ONLY the 4 allowlisted SQL views."""
from __future__ import annotations

import datetime
import zoneinfo

from app.config import Settings, get_settings

ALLOWLISTED_VIEWS: tuple[str, ...] = (
    "v_daily_summary",
    "v_commits",
    "v_screen_time",
    "v_reading",
)

_VIEW_SCHEMA_BLOCK = """
Available PostgreSQL views (read-only allowlist — query ONLY these 4 views):

1. v_daily_summary — one row per day combining health, activity, commits, reading, and screen time
   - date (date): Owner-local calendar date.
   - sleep_hours (numeric(4,2)): Hours slept on that date (nullable).
   - sleep_score (integer): Sleep quality score 0-100 (nullable).
   - deep_sleep_min (integer): Deep sleep duration in minutes (nullable).
   - hrv_ms (numeric(6,2)): Heart rate variability in milliseconds (nullable).
   - resting_hr (integer): Resting heart rate in beats per minute (nullable).
   - steps (integer): Total daily step count (nullable).
   - commits (bigint): Total git commits pushed on that date (0 if none).
   - lines_added (bigint): Total code lines added across commits on that date (0 if none).
   - pages_read (bigint): Total book pages read on that date (0 if none).
   - reading_minutes (bigint): Total minutes spent reading on that date (0 if none).
   - screen_minutes (bigint): Total screen time in minutes on that date (0 if none).

2. v_commits — individual git commit records (excludes commit message prose)
   - sha (text): Unique commit hash identifier.
   - repo (text): Repository slug (e.g. owner/repo).
   - committed_at (timestamptz): UTC commit timestamp.
   - commit_date (date): Owner-local calendar date of the commit.
   - additions (integer): Lines added in the commit.
   - deletions (integer): Lines deleted in the commit.

3. v_screen_time — daily screen usage broken down by category
   - date (date): Owner-local calendar date.
   - category (text): Category label (e.g. Productivity, Entertainment, Social).
   - minutes (integer): Minutes spent in that category on that date.

4. v_reading — daily reading sessions by book title
   - date (date): Owner-local calendar date.
   - title (text): Book title.
   - pages_read (integer): Number of pages read in that session.
   - minutes (integer): Minutes spent reading in that session.
""".strip()

_FEW_SHOT_EXAMPLES = """
Few-shot PostgreSQL examples (follow these exact view and SQL conventions):
- Question: What was my average sleep on days I pushed code?
  SQL: SELECT round(avg(sleep_hours),2) AS avg_sleep FROM v_daily_summary WHERE commits > 0;
- Question: Show my steps for the last 7 days.
  SQL: SELECT date, steps FROM v_daily_summary WHERE date >= current_date - 7 ORDER BY date;
- Question: What is the correlation between sleep hours and commits?
  SQL: SELECT round(corr(sleep_hours, commits)::numeric,3) AS r FROM v_daily_summary;
- Question: Show my weekly commit totals.
  SQL: SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits
       FROM v_daily_summary GROUP BY 1 ORDER BY 1;
- Question: What are my top screen time categories?
  SQL: SELECT category, sum(minutes) AS total FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
""".strip()


def build_schema_prompt(
    *,
    settings: Settings | None = None,
    today: datetime.date | None = None,
) -> str:
    """Build the system prompt for Text-to-SQL using allowlisted views only."""
    cfg = settings or get_settings()
    if today is None:
        tz = zoneinfo.ZoneInfo(cfg.app_timezone)
        today = datetime.datetime.now(tz).date()

    return (
        "You are a PostgreSQL Text-to-SQL assistant for personal analytics.\n"
        f"Today's date ({cfg.app_timezone}): {today.isoformat()}\n\n"
        f"{_VIEW_SCHEMA_BLOCK}\n\n"
        f"{_FEW_SHOT_EXAMPLES}\n\n"
        "Strict SQL rules:\n"
        "- Produce a single PostgreSQL SELECT statement (CTEs with WITH ... SELECT allowed).\n"
        "- Reference ONLY the 4 views listed above without schema prefixes.\n"
        "- Do NOT use UNION at top level; use CASE WHEN, FILTER, or CTEs in one SELECT.\n"
        "- Cast floating-point expressions to ::numeric before calling round(val::numeric, n).\n"
        "- Never include DDL, DML, comments with semicolons, INTO, FOR UPDATE, or LOCK.\n"
        "- Return JSON matching the schema: {\"sql\": \"...\", \"explanation\": \"...\"}."
    )
