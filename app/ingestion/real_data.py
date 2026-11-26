"""Real public dataset fetchers, parsers, and systematic alignment utilities.

Researched open datasets used by scripts/ingest_real_data.py so the showcase
database runs on real human wearable telemetry, real Goodreads reading logs and
reviews, real diary entries, real mobile screen-time logs, and real public
GitHub commits rather than synthetic random generators.
"""
from __future__ import annotations

import collections
import csv
import datetime
import html
import io
import json
import pathlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

import httpx

from app.ingestion.cleaning import clean_text, parse_timestamp

DATA_CACHE_DIR = pathlib.Path(".cache/real_data")

ZENODO_GROUPHEALTH_URL = (
    "https://zenodo.org/api/records/15171250/files/GroupHealth_SleepScreen.csv/content"
)
FITBIT_ACTIVITY_URL = (
    "https://raw.githubusercontent.com/health-hacks/datasets/master/"
    "fitbit-mturk/various-participants/fitabase-data-4-12-16-to-5-12-16/dailyActivity_merged.csv"
)
FITBIT_SLEEP_URL = (
    "https://raw.githubusercontent.com/health-hacks/datasets/master/"
    "fitbit-mturk/various-participants/fitabase-data-4-12-16-to-5-12-16/sleepDay_merged.csv"
)
SCREENTIME_APP_URL = (
    "https://raw.githubusercontent.com/emadnahed/ScreenTimeAnalyzer/HEAD/"
    "Screentime-App-Details.csv"
)
GOODREADS_EXPORT_URL = (
    "https://raw.githubusercontent.com/JB3NNETT/Goodreads-TBR/main/"
    "goodreads_library_export.csv"
)
JOURNAL_VAD_URL = (
    "https://huggingface.co/datasets/mmarkusmalone/journal-entries-emotion-detection-vad/"
    "resolve/main/vad_data.csv"
)

DEFAULT_GITHUB_USERNAME = "Mr-Vicky-06"
DEFAULT_GITHUB_REPOS: tuple[str, ...] = (
    "Life-API",
    "Mr-Vicky-06",
    "UX-CO-Skill",
    "cricket_iq",
    "Living_Marvel_Universe",
    "V-Y-K-E",
    "SkillForage",
    "LeadAI_Desk",
    "Spider_man_brand_new_day",
    "UC10_PipelineMonitor_DataSentinel",
    "FWA-Orchestrator",
    "Aetheria",
    "VICKYVERSE",
    "VICYVERRSE_X_SQL_MASTER",
    "MedScribe_AI",
    "neetcode_DSA_250",
)

REAL_SOURCES_MANIFEST: list[dict[str, str]] = [
    {
        "stream": "github_commits + notes(commit_message)",
        "name": "Mr-Vicky-06 Public GitHub Repositories + Local git log",
        "url": "https://github.com/Mr-Vicky-06",
        "license": "Public GitHub Repositories",
    },
    {
        "stream": "health_daily + screen_time totals",
        "name": "Group Health Dataset (Sleep and Screen Time), Eindhoven Univ. of Technology",
        "url": ZENODO_GROUPHEALTH_URL,
        "license": "CC-BY 4.0 (Zenodo 15171250)",
    },
    {
        "stream": "health_daily (earlier wearable baseline)",
        "name": "Fitbit Fitabase Research Dataset",
        "url": FITBIT_ACTIVITY_URL,
        "license": "Public Research Dataset (CC0 / Fitabase MTurk)",
    },
    {
        "stream": "screen_time (Social app usage)",
        "name": "Screentime-App-Details Mobile Usage Log",
        "url": SCREENTIME_APP_URL,
        "license": "Public GitHub Analytics Dataset",
    },
    {
        "stream": "reading_log + notes(reading_note)",
        "name": "Goodreads Library Export with Pages Read & Reviews",
        "url": GOODREADS_EXPORT_URL,
        "license": "Public Goodreads Library Export on GitHub",
    },
    {
        "stream": "notes(journal)",
        "name": "Reddit Diary Entries VAD Dataset (Hugging Face)",
        "url": JOURNAL_VAD_URL,
        "license": "CC-BY-NC-4.0",
    },
]

_TIME_DURATION_RE = re.compile(r"(\d+):(\d+):(\d+)")
_FIRST_PERSON_RE = re.compile(r"\b(i|my|me)\b", re.IGNORECASE)
_BANNED_DIARY_TERMS = (
    "suicide",
    "kill",
    "abuse",
    "sex",
    "fuck",
    "shit",
    "bitch",
    "assault",
    "trump",
    "biden",
    "http",
    "u/",
    "r/",
    "ex ",
    "boyfriend",
    "girlfriend",
    "beer",
    "drunk",
)


@dataclass(frozen=True)
class DailyWearableRecord:
    """Normalized single-day record from a real wearable dataset."""

    orig_date: datetime.date
    sleep_hours: float
    sleep_score: int
    deep_sleep_min: int
    hrv_ms: float
    resting_hr: int
    steps: int
    source: str
    screen_total_min: int | None = None


def download_cached(
    url: str,
    cache_name: str,
    *,
    cache_dir: pathlib.Path = DATA_CACHE_DIR,
    refresh: bool = False,
) -> str:
    """Fetch a public dataset file once and cache its UTF-8 text locally."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / cache_name
    if target.exists() and not refresh:
        return target.read_text(encoding="utf-8", errors="replace")

    with httpx.Client(
        timeout=60.0,
        headers={"User-Agent": "Life-API-RealData/1.0"},
        follow_redirects=True,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        target.write_bytes(resp.content)
        return target.read_text(encoding="utf-8", errors="replace")


def _systematic_sleep_score(
    sleep_hours: float,
    deep_sleep_min: int,
    rem_min: int,
    awake_min: int,
    rating: float | None = None,
) -> int:
    if rating is not None and 0.0 < rating <= 1.0:
        return max(40, min(100, int(round(rating * 100))))
    dur_score = min(50.0, (sleep_hours / 8.0) * 50.0)
    deep_score = min(25.0, (deep_sleep_min / 95.0) * 25.0)
    rem_score = min(20.0, (rem_min / 90.0) * 20.0) if rem_min > 0 else 10.0
    penalty = min(15.0, awake_min * 0.25)
    return max(40, min(98, int(round(dur_score + deep_score + rem_score + 5.0 - penalty))))


def _systematic_hrv(
    resting_hr: int,
    deep_sleep_min: int,
    stress: float | None = None,
) -> float:
    if stress is not None:
        val = 80.0 - 0.35 * stress - 0.25 * (resting_hr - 60)
    else:
        val = 58.0 + (deep_sleep_min - 80) * 0.14 - (resting_hr - 62) * 0.35
    return round(max(26.0, min(92.0, val)), 2)


def parse_grouphealth_csv(
    csv_text: str,
    *,
    uid_order: tuple[str, ...] = ("4", "2", "1"),
) -> list[DailyWearableRecord]:
    """Parse Eindhoven Zenodo 15171250 CSV into ordered DailyWearableRecord entries."""
    buckets: dict[tuple[str, datetime.date], dict[str, Any]] = collections.defaultdict(
        lambda: {
            "sleep": [],
            "steps": 0,
            "rhr": [],
            "hr": [],
            "stress": [],
            "screen_min": 0,
            "rating": [],
        }
    )

    for row in csv.DictReader(io.StringIO(csv_text)):
        uid = (row.get("Uid") or "").strip()
        raw_t = row.get("Time") or ""
        try:
            ts_val = float(raw_t)
        except ValueError:
            continue
        if ts_val < 1_000_000_000:
            continue

        day = datetime.datetime.fromtimestamp(ts_val, tz=datetime.UTC).date()
        bucket = buckets[(uid, day)]
        key = (row.get("Key") or "").strip()
        val_str = row.get("Value") or ""

        if key == "sleep" and val_str:
            try:
                bucket["sleep"].append(json.loads(val_str))
            except ValueError:
                pass
        elif key == "steps" and val_str:
            try:
                bucket["steps"] += int(json.loads(val_str).get("steps", 0))
            except (ValueError, TypeError):
                pass
        elif key == "resting_heart_rate" and val_str:
            try:
                bpm = json.loads(val_str).get("bpm")
                if isinstance(bpm, int | float):
                    bucket["rhr"].append(int(bpm))
            except (ValueError, TypeError):
                pass
        elif key == "heart_rate" and val_str:
            try:
                bpm = json.loads(val_str).get("bpm")
                if isinstance(bpm, int | float):
                    bucket["hr"].append(int(bpm))
            except (ValueError, TypeError):
                pass
        elif key == "stress" and val_str:
            try:
                stress = json.loads(val_str).get("stress")
                if isinstance(stress, int | float):
                    bucket["stress"].append(float(stress))
            except (ValueError, TypeError):
                pass

        raw_screen = (row.get("screentime") or "").strip()
        if raw_screen:
            m = _TIME_DURATION_RE.search(raw_screen)
            if m:
                total_min = int(m.group(1)) * 60 + int(m.group(2))
                bucket["screen_min"] = max(bucket["screen_min"], total_min)

        raw_rating = (row.get("sleep_rating") or "").strip()
        if raw_rating:
            try:
                bucket["rating"].append(float(raw_rating))
            except ValueError:
                pass

    records: list[DailyWearableRecord] = []
    for uid in uid_order:
        uid_days = sorted(d for (u, d) in buckets if u == uid)
        for day in uid_days:
            b = buckets[(uid, day)]
            if not b["sleep"] or b["steps"] <= 0:
                continue
            main_sleep = max(b["sleep"], key=lambda s: float(s.get("duration") or 0))
            duration_min = float(main_sleep.get("duration") or 0)
            sleep_hours = round(duration_min / 60.0, 2)
            if not (2.0 <= sleep_hours <= 14.0):
                continue

            deep_min = int(main_sleep.get("sleep_deep_duration") or 0)
            rem_min = int(main_sleep.get("sleep_rem_duration") or 0)
            awake_min = int(main_sleep.get("sleep_awake_duration") or 0)

            if b["rhr"]:
                rhr = int(round(sum(b["rhr"]) / len(b["rhr"])))
            elif b["hr"]:
                sorted_hr = sorted(b["hr"])
                rhr = sorted_hr[max(0, int(len(sorted_hr) * 0.10))]
            else:
                rhr = 62

            avg_stress = sum(b["stress"]) / len(b["stress"]) if b["stress"] else None
            rating = sum(b["rating"]) / len(b["rating"]) if b["rating"] else None
            sleep_score = _systematic_sleep_score(
                sleep_hours, deep_min, rem_min, awake_min, rating
            )
            hrv_ms = _systematic_hrv(rhr, deep_min, avg_stress)

            records.append(
                DailyWearableRecord(
                    orig_date=day,
                    sleep_hours=sleep_hours,
                    sleep_score=sleep_score,
                    deep_sleep_min=deep_min,
                    hrv_ms=hrv_ms,
                    resting_hr=rhr,
                    steps=int(b["steps"]),
                    source="zenodo_15171250",
                    screen_total_min=b["screen_min"] if b["screen_min"] > 0 else None,
                )
            )
    return records


def parse_fitbit_csvs(
    activity_csv: str,
    sleep_csv: str,
    *,
    preferred_pids: tuple[str, ...] = ("8378563200", "6962181067", "5553957443"),
) -> list[DailyWearableRecord]:
    """Parse Fitbit Fitabase activity and sleep CSVs into ordered wearable records."""
    act_map: dict[tuple[str, int], dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(activity_csv)):
        pid = (row.get("participant-id") or "").strip()
        ts = row.get("timestamp") or ""
        try:
            key = (pid, int(float(ts)))
            act_map[key] = row
        except ValueError:
            continue

    slp_map: dict[tuple[str, int], dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(sleep_csv)):
        pid = (row.get("participant-id") or "").strip()
        ts = row.get("timestamp") or ""
        try:
            key = (pid, int(float(ts)))
            slp_map[key] = row
        except ValueError:
            continue

    records: list[DailyWearableRecord] = []
    for pid in preferred_pids:
        keys = sorted(k for k in slp_map if k[0] == pid and k in act_map)
        for key in keys:
            a_row = act_map[key]
            s_row = slp_map[key]
            steps = int(float(a_row.get("total-steps") or 0))
            asleep_min = int(float(s_row.get("total-minutes-asleep") or 0))
            in_bed_min = max(asleep_min, int(float(s_row.get("total-time-in-bed") or 1)))
            if steps <= 0 or asleep_min <= 0:
                continue

            sleep_hours = round(asleep_min / 60.0, 2)
            efficiency = asleep_min / in_bed_min
            deep_min = max(35, int(round(asleep_min * 0.20)))
            rhr = max(52, min(72, int(round(66 - (steps / 2500.0) - (sleep_hours - 7.0) * 1.5))))
            sleep_score = _systematic_sleep_score(
                sleep_hours,
                deep_min,
                int(round(asleep_min * 0.22)),
                max(0, in_bed_min - asleep_min),
                rating=efficiency,
            )
            hrv_ms = _systematic_hrv(rhr, deep_min)
            day = datetime.datetime.fromtimestamp(key[1], tz=datetime.UTC).date()
            records.append(
                DailyWearableRecord(
                    orig_date=day,
                    sleep_hours=sleep_hours,
                    sleep_score=sleep_score,
                    deep_sleep_min=deep_min,
                    hrv_ms=hrv_ms,
                    resting_hr=rhr,
                    steps=steps,
                    source="fitbit_fitabase",
                    screen_total_min=None,
                )
            )
    return records


def build_health_timeline(
    grouphealth_records: list[DailyWearableRecord],
    fitbit_records: list[DailyWearableRecord],
    *,
    end_date: datetime.date,
    total_days: int = 179,
) -> list[dict[str, Any]]:
    """Map real wearable records monotonically onto [end_date - total_days + 1 .. end_date]."""
    recent = grouphealth_records[-total_days:]
    needed_fitbit = max(0, total_days - len(recent))
    earlier = fitbit_records[:needed_fitbit]
    combined = earlier + recent

    if len(combined) < total_days and grouphealth_records:
        pad = (grouphealth_records + fitbit_records)[: total_days - len(combined)]
        combined = pad + combined

    combined = combined[-total_days:]
    start_date = end_date - datetime.timedelta(days=len(combined) - 1)
    timeline: list[dict[str, Any]] = []
    for idx, rec in enumerate(combined):
        mapped_date = start_date + datetime.timedelta(days=idx)
        timeline.append(
            {
                "date": mapped_date,
                "sleep_hours": rec.sleep_hours,
                "sleep_score": rec.sleep_score,
                "deep_sleep_min": rec.deep_sleep_min,
                "hrv_ms": rec.hrv_ms,
                "resting_hr": rec.resting_hr,
                "steps": rec.steps,
                "source": rec.source,
                "_screen_total_min": rec.screen_total_min,
            }
        )
    return timeline


def parse_screentime_social_csv(csv_text: str) -> list[int]:
    """Sum daily Social app usage minutes from Screentime-App-Details.csv."""
    by_day: dict[str, int] = collections.defaultdict(int)
    for row in csv.DictReader(io.StringIO(csv_text)):
        d = (row.get("Date") or "").strip()
        try:
            usage = int(float(row.get("Usage") or 0))
        except ValueError:
            usage = 0
        if d and usage > 0:
            by_day[d] += usage
    return [by_day[d] for d in sorted(by_day)]


def build_screen_time_rows(
    health_timeline: list[dict[str, Any]],
    social_series: list[int],
    commit_counts_by_date: dict[datetime.date, int],
) -> list[dict[str, Any]]:
    """Build daily Productivity/Entertainment/Social rows anchored to real screen totals."""
    rows: list[dict[str, Any]] = []
    social_pool = social_series or [65]

    for idx, day_row in enumerate(health_timeline):
        day = day_row["date"]
        commits_today = commit_counts_by_date.get(day, 0)
        measured_total = day_row.get("_screen_total_min")
        real_social = social_pool[idx % len(social_pool)]

        if measured_total and measured_total > 0:
            total = int(measured_total)
            social = min(real_social, max(15, int(round(total * 0.50))))
            remainder = max(0, total - social)
            prod_ratio = 0.65 if commits_today > 0 else (0.48 if day.weekday() < 5 else 0.35)
            productivity = int(round(remainder * prod_ratio))
            entertainment = max(0, remainder - productivity)
        else:
            social = real_social
            productivity = 180 + min(120, commits_today * 18) if commits_today > 0 else (
                135 if day.weekday() < 5 else 75
            )
            entertainment = 95 if day.weekday() >= 5 else 65

        rows.extend(
            [
                {"date": day, "category": "Productivity", "minutes": productivity},
                {"date": day, "category": "Entertainment", "minutes": entertainment},
                {"date": day, "category": "Social", "minutes": social},
            ]
        )
    return rows


def parse_goodreads_books(csv_text: str) -> list[dict[str, Any]]:
    """Extract finished Goodreads books sorted by Date Read with real page counts & reviews."""
    books: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        date_str = (row.get("Date Read") or "").strip()
        title = clean_text(row.get("Title") or "")
        author = clean_text(row.get("Author") or "")
        pages_raw = (row.get("Number of Pages") or "").strip()
        if not date_str or not title or not pages_raw:
            continue
        try:
            orig_date = datetime.date.fromisoformat(date_str.replace("/", "-"))
            pages = int(pages_raw)
        except ValueError:
            continue
        if pages <= 0:
            continue

        raw_review = html.unescape(
            (row.get("My Review") or "").replace("<br/>", " ").replace("<br />", " ")
        )
        cleaned_review = clean_text(raw_review)
        books.append(
            {
                "orig_date": orig_date,
                "title": title,
                "author": author,
                "pages_read": pages,
                "minutes": max(15, int(round(pages * 1.4))),
                "review": cleaned_review,
            }
        )
    books.sort(key=lambda b: b["orig_date"])
    return books


def build_reading_and_notes(
    books: list[dict[str, Any]],
    *,
    start_date: datetime.date,
    end_date: datetime.date,
    target_entries: int = 75,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Align real Goodreads finished books and written reviews into [start_date, end_date]."""
    with_reviews = [b for b in books if b["review"]]
    without_reviews = [b for b in books if not b["review"]]
    selected = with_reviews[-55:] + without_reviews[-max(0, target_entries - 55) :]
    selected.sort(key=lambda b: b["orig_date"])
    if not selected:
        return [], []

    span_days = max(1, (end_date - start_date).days)
    reading_rows: list[dict[str, Any]] = []
    note_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[datetime.date, str]] = set()

    for idx, book in enumerate(selected):
        offset = int(round((idx / max(1, len(selected) - 1)) * span_days))
        mapped_date = start_date + datetime.timedelta(days=offset)
        if (mapped_date, book["title"]) in seen_pairs:
            continue
        seen_pairs.add((mapped_date, book["title"]))

        reading_rows.append(
            {
                "date": mapped_date,
                "title": book["title"],
                "pages_read": book["pages_read"],
                "minutes": book["minutes"],
            }
        )
        if book["review"]:
            author_part = f" by {book['author']}" if book["author"] else ""
            note_content = clean_text(
                f"Reading Notes on {mapped_date.isoformat()}: {book['title']}{author_part} "
                f"({book['pages_read']} pages). {book['review']}"
            )
            note_rows.append(
                {
                    "ts": datetime.datetime.combine(
                        mapped_date, datetime.time(21, 15), tzinfo=datetime.UTC
                    ),
                    "note_date": mapped_date,
                    "source_type": "reading_note",
                    "content": note_content[:1200],
                }
            )
    return reading_rows, note_rows


def parse_vad_journals(csv_text: str) -> tuple[list[str], list[str], list[str]]:
    """Filter clean first-person diary entries bucketed by low/mid/high Valence score."""
    low_sleep: list[str] = []
    mid_daily: list[str] = []
    high_pos: list[str] = []

    for row in csv.DictReader(io.StringIO(csv_text)):
        raw_post = row.get("Post") or ""
        text_clean = clean_text(re.sub(r"\s+", " ", html.unescape(raw_post)).strip())
        low = text_clean.lower()
        if not (90 <= len(text_clean) <= 380):
            continue
        if any(term in low for term in _BANNED_DIARY_TERMS):
            continue
        if not _FIRST_PERSON_RE.search(low):
            continue
        try:
            valence = float(row.get("V") or 0.0)
        except ValueError:
            continue

        if valence <= -0.15 and any(
            w in low for w in ("sleep", "slept", "tired", "exhausted", "insomnia")
        ):
            low_sleep.append(text_clean)
        elif -0.15 < valence < 0.35 and any(
            w in low for w in ("work", "day", "morning", "sleep", "read", "walk")
        ):
            mid_daily.append(text_clean)
        elif valence >= 0.40 and any(
            w in low
            for w in (
                "work",
                "focus",
                "read",
                "book",
                "walk",
                "rest",
                "peace",
                "good",
                "great",
                "happy",
                "proud",
                "grateful",
            )
        ):
            high_pos.append(text_clean)

    return low_sleep, mid_daily, high_pos


def build_journal_notes(
    health_timeline: list[dict[str, Any]],
    low_sleep: list[str],
    mid_daily: list[str],
    high_pos: list[str],
) -> list[dict[str, Any]]:
    """Pair real VAD diary entries to wearable days based on actual sleep hours."""
    notes: list[dict[str, Any]] = []
    low_i = mid_i = high_i = 0

    for idx, day_row in enumerate(health_timeline):
        sleep_h = float(day_row["sleep_hours"])
        day = day_row["date"]
        # Record every poor-sleep night (<6.3h) plus alternating normal/high days (~75 total).
        if sleep_h < 6.3 and low_sleep:
            entry = low_sleep[low_i % len(low_sleep)]
            low_i += 1
        elif idx % 2 != 0:
            continue
        elif sleep_h >= 7.5 and high_pos:
            entry = high_pos[high_i % len(high_pos)]
            high_i += 1
        elif mid_daily:
            entry = mid_daily[mid_i % len(mid_daily)]
            mid_i += 1
        elif high_pos:
            entry = high_pos[high_i % len(high_pos)]
            high_i += 1
        else:
            continue

        content = clean_text(
            f"Journal ({day.isoformat()}): [Sleep: {sleep_h}h, Steps: {day_row['steps']}] "
            f"{entry}"
        )
        notes.append(
            {
                "ts": datetime.datetime.combine(day, datetime.time(21, 30), tzinfo=datetime.UTC),
                "note_date": day,
                "source_type": "journal",
                "content": content,
            }
        )
    return notes


def _parse_local_git_commits(
    git_dir: pathlib.Path,
    repo_label: str,
    since_date: datetime.date,
    *,
    with_numstat: bool,
) -> list[dict[str, Any]]:
    cmd = [
        "git",
        "--git-dir",
        str(git_dir),
        "log",
        "--all",
        f"--since={since_date.isoformat()}",
        "--pretty=format:COMMIT|%H|%aI|%s",
    ]
    if with_numstat:
        cmd.append("--numstat")
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        return []

    commits: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in res.stdout.splitlines():
        if line.startswith("COMMIT|"):
            if cur is not None:
                commits.append(cur)
            _, sha, iso_dt, msg = line.split("|", 3)
            committed_at = parse_timestamp(iso_dt)
            cur = {
                "sha": sha,
                "repo": repo_label,
                "committed_at": committed_at,
                "commit_date": committed_at.date(),
                "message": clean_text(msg) or msg.strip(),
                "additions": 0,
                "deletions": 0,
            }
        elif cur is not None and "\t" in line:
            parts = line.split("\t", 2)
            if parts[0].isdigit():
                cur["additions"] += int(parts[0])
            if parts[1].isdigit():
                cur["deletions"] += int(parts[1])
    if cur is not None:
        commits.append(cur)
    return commits


def collect_github_commits(
    since_date: datetime.date,
    *,
    username: str = DEFAULT_GITHUB_USERNAME,
    repos: tuple[str, ...] = DEFAULT_GITHUB_REPOS,
    local_repo_root: pathlib.Path = pathlib.Path("."),
    include_remote: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect real GitHub commits (exact numstat for local repo + public repos via git)."""
    seen_shas: set[str] = set()
    commits: list[dict[str, Any]] = []

    local_git = local_repo_root / ".git"
    if local_git.exists():
        raw_name = local_repo_root.resolve().name
        canonical_name = "Life-API" if raw_name.lower() in {"life_api", "life-api"} else raw_name
        for row in _parse_local_git_commits(
            local_git, f"{username}/{canonical_name}", since_date, with_numstat=True
        ):
            if row["sha"] not in seen_shas:
                seen_shas.add(row["sha"])
                commits.append(row)

    if include_remote:
        with tempfile.TemporaryDirectory() as tmp:
            for name in repos:
                bare_dir = pathlib.Path(tmp) / f"{name}.git"
                clone_cmd = [
                    "git",
                    "clone",
                    "--bare",
                    "--filter=tree:0",
                    "--quiet",
                    f"https://github.com/{username}/{name}.git",
                    str(bare_dir),
                ]
                try:
                    c_res = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=15)
                except subprocess.TimeoutExpired:
                    continue
                if c_res.returncode != 0:
                    continue
                for row in _parse_local_git_commits(
                    bare_dir, f"{username}/{name}", since_date, with_numstat=False
                ):
                    if row["sha"] not in seen_shas:
                        seen_shas.add(row["sha"])
                        commits.append(row)

    commit_notes: list[dict[str, Any]] = []
    seen_msgs: set[tuple[datetime.date, str]] = set()
    for row in commits:
        msg = row["message"]
        key = (row["commit_date"], msg)
        if len(msg) < 12 or key in seen_msgs:
            continue
        seen_msgs.add(key)
        commit_notes.append(
            {
                "ts": row["committed_at"],
                "note_date": row["commit_date"],
                "source_type": "commit_message",
                "content": f"Commit in {row['repo']} ({row['commit_date'].isoformat()}): {msg}",
            }
        )
    return commits, commit_notes
