# Real Open-Dataset Showcase Provenance Report
Date: 2026-11-26 | Branch: feat/real-showcase-data | Status: Verified

## 1. Objective

Replace synthetic seeded showcase rows in the live Streamlit database (`life`) with verified public real-world datasets and real owner GitHub commit histories (`python -m scripts.ingest_real_data --reset`), keeping `python -m scripts.seed` (`random.seed(42)`) intact strictly for deterministic automated tests.

---

## 2. Verified Real Data Sources & Systematic Derivations

| Table / Stream | Primary Real Source | License / Provenance | Records Loaded | Honest Handling / Derivations |
|---|---|---|---|---|
| `github_commits` + `notes (commit_message)` | `Mr-Vicky-06` active public GitHub repositories (`Life-API`, `UC10_PipelineMonitor_DataSentinel`, `neetcode_DSA_250`, `V-Y-K-E`, `cricket_iq`, `SkillForage`, `Aetheria`, `Spider_man_brand_new_day`, `Mr-Vicky-06`, `Living_Marvel_Universe`, `MedScribe_AI`, `UX-CO-Skill`, `FWA-Orchestrator`, `VICKYVERSE`, `VICYVERRSE_X_SQL_MASTER`) | Public GitHub repositories (`github.com/Mr-Vicky-06`) | 203 real commits (`2026-06-01..2026-11-26`) | Native 2026 commit timestamps & SHAs preserved verbatim; exact `additions`/`deletions` extracted via `git log --numstat` locally (`Life-API`) and `0` fallback when shallow remote header clones (`--filter=tree:0`) skip diffs. |
| `health_daily` (recent 117 days) | [Group Health Dataset (Sleep and Screen Time)](https://zenodo.org/api/records/15171250/files/GroupHealth_SleepScreen.csv/content) — Eindhoven Univ. of Technology (Zenodo `15171250`, `2025-04-08`) | `CC-BY 4.0` | 117 real participant-days (`UID 4`, `UID 2`, `UID 1`) | Measured `sleep` duration/deep/light/REM, `steps`, `resting_heart_rate` (or nocturnal 10th-pct watch HR), `stress`, `sleep_rating`, and total `screentime`. Calendar-aligned onto recent days ending `2026-11-26` (putting `UID 1` on the most recent 37 days). Missing watch `sleep_rating` -> systematic score from measured duration/deep/REM/awake; `hrv_ms` derived systematically from wearable `stress` + `resting_hr`. |
| `health_daily` (earlier 62 days) | [Fitbit Fitabase Research Dataset](https://raw.githubusercontent.com/health-hacks/datasets/master/fitbit-mturk/various-participants/fitabase-data-4-12-16-to-5-12-16/dailyActivity_merged.csv) (`dailyActivity_merged.csv` + `sleepDay_merged.csv`) | Public Research Dataset (MTurk / Fitabase) | 62 real paired participant-days | Measured `total-steps` and `total-minutes-asleep` (`sleep_hours`), aligned onto `2026-06-01..2026-08-01`; `deep_sleep_min`, `resting_hr`, and `hrv_ms` systematically estimated from measured sleep efficiency and step volume. |
| `screen_time` | GroupHealth `screentime` totals + [Screentime-App-Details.csv](https://raw.githubusercontent.com/emadnahed/ScreenTimeAnalyzer/HEAD/Screentime-App-Details.csv) | `CC-BY 4.0` + Public Mobile Screen-Time Log | 537 category rows across 179 days | Uses real measured GroupHealth daily `screentime` totals where present (`<= 81` days) and real `Instagram` + `Whatsapp` daily `Social` totals from `Screentime-App-Details.csv`; remaining measured minutes split cleanly into `Productivity` vs `Entertainment` weighted by real GitHub commit activity (`Productivity` + `Entertainment` + `Social` equals measured total). |
| `reading_log` + `notes (reading_note)` | [JB3NNETT/Goodreads-TBR/goodreads_library_export.csv](https://raw.githubusercontent.com/JB3NNETT/Goodreads-TBR/main/goodreads_library_export.csv) | Public Goodreads Library Export | 75 real finished books + HTML-cleaned written reviews | Preserves real titles, authors, `Number of Pages` -> `pages_read`, and real `My Review` text cleaned via `html.unescape` + `clean_text`; systematically derives `reading_log.minutes = round(pages_read * 1.4)` and maps dates across `2026-06-01..2026-11-26`. |
| `notes (journal)` | [mmarkusmalone/journal-entries-emotion-detection-vad](https://huggingface.co/datasets/mmarkusmalone/journal-entries-emotion-detection-vad/resolve/main/vad_data.csv) | `CC-BY-NC-4.0` | Filtered clean first-person diary entries (part of 364 total `notes`) | Authentic first-person diary posts filtered for clean non-profane daily-life prose and matched by continuous Valence (`V`) score to short-sleep (`< 6.3h`) vs rested/active wearable days. |

---

## 3. Verification Gates (Latest Run)

```text
.\.venv\Scripts\python.exe -m scripts.ingest_real_data --reset
Real data ingest completed (2026-06-01..2026-11-26): health=179ins/0upd, commits=203ins/0upd, reading=75ins/0upd, screen=537ins/0upd, notes=364ins/0skip

.\.venv\Scripts\python.exe -m ruff check dashboard/ app/metrics.py app/schemas/metrics.py app/api/routes_metrics.py app/ingestion/real_data.py scripts/ingest_real_data.py tests/integration/test_metrics.py tests/unit/test_dashboard_charts.py tests/unit/test_dashboard_client.py tests/integration/test_dashboard_app.py tests/unit/test_real_data.py
All checks passed!

.\.venv\Scripts\python.exe -m pytest -q
196 passed, 2 warnings in 293.02s (0:04:53)
```

Live Playwright Dashboard Verification (against PostgreSQL `life` + Ollama `qwen2.5-coder:7b` + `http://127.0.0.1:8501`):
- `Overview`: `Available data: 2026-06-01 to 2026-11-26`, default 30d window (`2026-10-28..2026-11-26`) rendered `Avg Sleep 7.29 h (+0.40 h)`, `Total Commits 83 (+83)`, `Avg Steps 4,998 (-204)`, `Total Reading 6,684 min (+182 min)`, scatter `r = 0.275, n = 30`.
- `Date range filter`: Selecting `2026-09-01..2026-09-30` in sidebar calendar dynamically updated charts and KPIs (`0` browser console errors).
- `Daily Insight` (`2026-11-26`): Warm click rendered exact DB summary (`8.27 hours`, `470 minutes`, `54 steps`, `1` commit, `560 minutes` screen time); cold load prior to warm-up hit the 30 s data timeout cleanly with retry banner.
- `Search Notes` (`"slept tired"`): Returned real human diary hits matching short-sleep Eindhoven nights (`2026-11-23 | journal | score=0.0164`, `2026-10-16 | journal | score=0.0159`).
- `AI Chat` (`"What was my average sleep on days I pushed code?"`): Returned `7.41 hours` with expanded `Steps (2) | Latency: 12633 ms` and executed SQL over real commit + wearable days.
