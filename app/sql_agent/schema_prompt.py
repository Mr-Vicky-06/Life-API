"""Schema prompt builder exposing ONLY the 4 allowlisted SQL views."""
from __future__ import annotations

import datetime
import re
import zoneinfo

from app.config import Settings, get_settings

ALLOWLISTED_VIEWS: tuple[str, ...] = (
    "v_daily_summary",
    "v_commits",
    "v_screen_time",
    "v_reading",
)

VIEW_COLUMNS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "v_daily_summary": (
        "one row per day combining health, activity, commits, reading, and screen time",
        [
            ("date", "date", "Owner-local calendar date."),
            ("sleep_hours", "numeric(4,2)", "Hours slept on that date (nullable)."),
            ("sleep_score", "integer", "Sleep quality score 0-100 (nullable)."),
            ("deep_sleep_min", "integer", "Deep sleep duration in minutes (nullable)."),
            ("hrv_ms", "numeric(6,2)", "Heart rate variability in milliseconds (nullable)."),
            ("resting_hr", "integer", "Resting heart rate in beats per minute (nullable)."),
            ("steps", "integer", "Total daily step count (nullable)."),
            ("commits", "bigint", "Total git commits pushed on that date (0 if none)."),
            ("lines_added", "bigint", "Total code lines added on that date (0 if none)."),
            ("pages_read", "bigint", "Total book pages read on that date (0 if none)."),
            ("reading_minutes", "bigint", "Total minutes spent reading on that date (0 if none)."),
            ("screen_minutes", "bigint", "Total screen time in minutes on that date (0 if none)."),
        ],
    ),
    "v_commits": (
        "individual git commit records (excludes commit message prose)",
        [
            ("sha", "text", "Unique commit hash identifier."),
            ("repo", "text", "Repository slug (e.g. owner/repo)."),
            ("committed_at", "timestamptz", "UTC commit timestamp."),
            ("commit_date", "date", "Owner-local calendar date of the commit."),
            ("additions", "integer", "Lines added in the commit."),
            ("deletions", "integer", "Lines deleted in the commit."),
        ],
    ),
    "v_screen_time": (
        "daily screen usage broken down by category",
        [
            ("date", "date", "Owner-local calendar date."),
            ("category", "text", "Category label (e.g. Productivity, Entertainment, Social)."),
            ("minutes", "integer", "Minutes spent in that category on that date."),
        ],
    ),
    "v_reading": (
        "daily reading sessions by book title",
        [
            ("date", "date", "Owner-local calendar date."),
            ("title", "text", "Book title."),
            ("pages_read", "integer", "Number of pages read in that session."),
            ("minutes", "integer", "Minutes spent reading in that session."),
        ],
    ),
}

_VIEW_REF_RE = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in ALLOWLISTED_VIEWS) + r")\b",
    re.IGNORECASE,
)


def _render_view_schema_block() -> str:
    sections: list[str] = [
        "Available PostgreSQL views (read-only allowlist — query ONLY these 4 views):"
    ]
    for idx, view_name in enumerate(ALLOWLISTED_VIEWS, start=1):
        desc, cols = VIEW_COLUMNS[view_name]
        lines = [f"{idx}. {view_name} — {desc}"]
        for col_name, col_type, col_desc in cols:
            lines.append(f"   - {col_name} ({col_type}): {col_desc}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def format_view_columns_for_sql(sql: str) -> str:
    """Return exact column lists for every allowlisted view referenced in sql."""
    matched: list[str] = []
    seen: set[str] = set()
    for match in _VIEW_REF_RE.finditer(sql or ""):
        vname = match.group(1).lower()
        if vname not in seen and vname in VIEW_COLUMNS:
            seen.add(vname)
            matched.append(vname)

    targets = matched if matched else list(ALLOWLISTED_VIEWS)
    lines = ["Exact columns for referenced views:"]
    for vname in targets:
        _, cols = VIEW_COLUMNS[vname]
        col_list = ", ".join(f"{name} ({ctype})" for name, ctype, _ in cols)
        lines.append(f"- {vname}: {col_list}")
    return "\n".join(lines)


def get_reference_date(settings: Settings | None = None) -> datetime.date:
    """Return configured REFERENCE_DATE or today's date in APP_TIMEZONE."""
    cfg = settings or get_settings()
    if cfg.reference_date is not None:
        return cfg.reference_date
    tz = zoneinfo.ZoneInfo(cfg.app_timezone)
    return datetime.datetime.now(tz).date()


_STATIC_FEW_SHOT_EXAMPLES = """
Few-shot PostgreSQL examples (use these exact view and SQL conventions):
- Question: What was my average sleep on days I pushed code?
  SQL: SELECT round(avg(sleep_hours),2) AS avg_sleep FROM v_daily_summary WHERE commits > 0;
- Question (relative window): Show my steps for the last 7 days ending on REFERENCE_DATE.
  SQL: SELECT date, steps FROM v_daily_summary
       WHERE date > DATE '<REFERENCE_DATE>' - 7 AND date <= DATE '<REFERENCE_DATE>' ORDER BY date;
- Question: What is the correlation between sleep hours and commits?
  SQL: SELECT round(corr(sleep_hours, commits)::numeric,3) AS r FROM v_daily_summary;
- Question: Show my weekly commit totals.
  SQL: SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits
       FROM v_daily_summary GROUP BY 1 ORDER BY 1;
- Question: What are my top screen time categories?
  SQL: SELECT category, sum(minutes) AS total FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
- Question (argmax row): Which day had the highest reading_minutes?
  SQL: SELECT date, reading_minutes FROM v_daily_summary
       WHERE reading_minutes > 0 ORDER BY reading_minutes DESC LIMIT 1;
- Question (compare two groups): Compare avg sleep_score when reading_minutes > 60 vs <= 60.
  SQL: SELECT round(avg(sleep_score) FILTER (WHERE reading_minutes > 60)::numeric, 2) AS high_read,
              round(avg(sleep_score) FILTER (WHERE reading_minutes <= 60)::numeric, 2) AS low_read
       FROM v_daily_summary;
- Question (streak): Longest consecutive-day streak with reading_minutes >= 30?
  SQL: WITH active_days AS (
         SELECT date, date - (row_number() OVER (ORDER BY date))::int AS grp
         FROM v_daily_summary WHERE reading_minutes >= 30
       ), streaks AS (
         SELECT count(*) AS streak_len FROM active_days GROUP BY grp
       ) SELECT coalesce(max(streak_len), 0) AS longest_streak FROM streaks;
""".strip()


_STATIC_PREFIX_CACHE: str | None = None


def build_static_schema_prefix() -> str:
    """Return the static schema, few-shot examples, and strict SQL rules first for KV caching."""
    global _STATIC_PREFIX_CACHE
    if _STATIC_PREFIX_CACHE is None:
        schema_block = _render_view_schema_block()
        _STATIC_PREFIX_CACHE = (
            "You are a PostgreSQL Text-to-SQL assistant for personal analytics.\n\n"
            f"{schema_block}\n\n"
            f"{_STATIC_FEW_SHOT_EXAMPLES}\n\n"
            "Strict SQL rules:\n"
            "- Produce a single PostgreSQL SELECT statement (CTEs with WITH ... SELECT allowed).\n"
            "- Reference ONLY the 4 views listed above without schema prefixes.\n"
            "- Substitute <REFERENCE_DATE> with the exact Reference Date given at the end.\n"
            "- Apply a date WHERE filter ONLY when the question asks for a timeframe or date "
            "range; otherwise query ALL dates without any date filter (and omit LIMIT unless "
            "asked for top/highest/lowest N).\n"
            "- Relative-date convention: 'last N days' means N calendar days including "
            "<REFERENCE_DATE>: use `date > DATE '<REFERENCE_DATE>' - N AND "
            "date <= DATE '<REFERENCE_DATE>'` (never rely on CURRENT_DATE).\n"
            "- Weekday/weekend convention: weekend = Saturday and Sunday "
            "(EXTRACT(DOW FROM date) IN (0, 6)); weekdays = Monday-Friday "
            "(EXTRACT(DOW FROM date) BETWEEN 1 AND 5).\n"
            "- For argmax/argmin ('which day had the highest/lowest X'), use ORDER BY col "
            "DESC/ASC LIMIT 1 (do NOT use GROUP BY date with MAX/MIN).\n"
            "- For comparing two groups, use conditional aggregation AVG(x) FILTER (WHERE ...) "
            "in one SELECT (never self-join a view).\n"
            "- Do NOT use UNION at top level; use CASE WHEN, FILTER, or CTEs in one SELECT.\n"
            "- For medians use percentile_cont(0.5) WITHIN GROUP (ORDER BY col).\n"
            "- Cast numerators to ::numeric before division or calling round(val::numeric, n).\n"
            "- Keep explanation to one short sentence (max 15 words).\n"
            "- Never include DDL, DML, comments with semicolons, INTO, FOR UPDATE, or LOCK.\n"
            "- Return JSON matching the schema: {\"sql\": \"...\", \"explanation\": \"...\"}."
        )
    return _STATIC_PREFIX_CACHE


def build_date_context(
    *,
    settings: Settings | None = None,
    today: datetime.date | None = None,
) -> str:
    """Return the dynamic reference-date suffix placed at the end for KV prefix caching."""
    cfg = settings or get_settings()
    ref_date = today or get_reference_date(cfg)
    ref_iso = ref_date.isoformat()
    return f"Reference Date ({cfg.app_timezone}): {ref_iso}"


def build_schema_prompt(
    *,
    settings: Settings | None = None,
    today: datetime.date | None = None,
) -> str:
    """Build full system prompt with static schema/examples first and reference date last."""
    cfg = settings or get_settings()
    ref_date = today or get_reference_date(cfg)
    ref_iso = ref_date.isoformat()
    prefix = build_static_schema_prefix().replace("<REFERENCE_DATE>", ref_iso)
    suffix = build_date_context(settings=cfg, today=ref_date)
    return f"{prefix}\n\n{suffix}"
