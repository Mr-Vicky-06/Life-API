# Phase 5.1: SQL Accuracy Hardening & Safer Summaries
Date: 2026-11-25 | Branch: phase-5-1-sql-accuracy | Status: Stopped in Section D (`qwen2.5-coder:7b` missing in Ollama)

## 1. Objective

Harden Phase 5 Text-to-SQL accuracy and summary safety prior to Phase 6:
- **A. Reference Date Alignment**: Confirm Q02 anchor drift hypothesis, introduce `REFERENCE_DATE` (defaults to today in `APP_TIMEZONE`), and standardize `"last N days"` as `N` calendar days including the reference date (`date > ref - N AND date <= ref`).
- **B. Generic Prompt Patterns**: Add generic PostgreSQL pattern examples (argmax row, conditional aggregation via `FILTER`, gaps-and-islands streaks, A.3 relative windows) without copying golden or held-out questions.
- **C. Held-out Benchmark (`tests/golden/heldout.py`)**: Add 12 brand-new unseen questions with independent Python oracle computation and extend `scripts/bench_sql.py` with `--set golden|heldout|both` and `--model`.
- **D. Model Comparison (`ollama/llama3.1:8b` vs `ollama/qwen2.5-coder:7b`)**: Benchmark `both` sets (22 questions) on each model and apply the switching rule (`+2` held-out accuracy and `<= 1.5x` mean latency). **Note:** `qwen2.5-coder:7b` is not present in local Ollama; stopped Section D cleanly with the exact HTTP 404 error.
- **E. Safer Summaries & Stage Timings**: Use deterministic templates without LLM calls for single-row `<= 3` column results or any `< 5`-cell result; verify every number cited in multi-row LLM summaries appears in returned rows (falling back to a value-listing template otherwise); log per-stage timings (`generate`, `validate`, `execute`, `summarize`).
- **F. Documentation**: Update `docs/DATA_AND_RAG.md` §7, `docs/API_SPEC.md`, and `docs/DECISIONS.md`.

---

## 2. Part A: Reference Date Proof & Convention

Computed Q02 (`"total commits in the last 30 days"`) under both anchors on the fixed seed ending `2026-11-23`:
```text
Anchor 2026-11-23 (anchor-30 = 2026-10-24):
  date > anchor - 30  (30d inclusive window) : 116 (unbounded upper: 116)
  date >= anchor - 30 (31d window if <=anchor): 119
Anchor 2026-11-25 (anchor-30 = 2026-10-26):
  date > anchor - 30  (30d inclusive window) : 104 (unbounded upper: 104)
  date >= anchor - 30 (31d window if <=anchor): 115
```
Confirmed: Phase 5's `CURRENT_DATE - 30` evaluated `date >= 2026-10-26` (giving `115`), whereas the 30-day window ending on `2026-11-23` under `date > DATE '2026-11-23' - 30` is `116`. Setting `REFERENCE_DATE=2026-11-23` in golden tests and `bench_sql.py` aligned Q02 (giving `116` on `llama3.1:8b`).

---

## 3. What Was Built

- `app/config.py`, `.env.example`, `.env`: Added optional `REFERENCE_DATE` (empty defaults to today in `APP_TIMEZONE`).
- `app/sql_agent/schema_prompt.py`: Added `get_reference_date()`, A.3 `"last N days"` convention (`date > DATE '<ref>' - N AND date <= DATE '<ref>'`), and generic pattern examples (`reading_minutes` argmax, `sleep_score` / `reading_minutes` `FILTER` comparison, `reading_minutes >= 30` streak, `percentile_cont(0.5)` median syntax hint) with zero base-table or held-out leakage.
- `app/api/routes_query.py`: Added `build_template_summary()`, `verify_summary_numbers()`, `summarize_results()`, and per-stage latency logging (`generate`, `validate`, `execute`, `summarize`, no prompt text).
- `app/main.py` & `migrations/env.py`: Configured `app` logger at `INFO` level with redaction filter active and set `disable_existing_loggers=False` in Alembic so `v1/query stage timings` logs are preserved.
- `tests/golden/heldout.py` & `tests/golden/test_heldout_sql.py`: 12 new unseen benchmark questions covering weekday/weekend `EXTRACT(DOW)`, median `percentile_cont`, zero-commit count, `lines_added` range, `steps >= 8000` streak, monthly grouping, low-sleep top screen category join, percentage, per-repo commits, top book pages, lowest `resting_hr`, and 14-day commits.
- `tests/unit/test_summary.py` & `tests/integration/test_query.py`: Unit & integration tests verifying zero LLM calls on small results (`0`, `1x1`, `1x3`, `2x2`), valid rounded LLM summary pass-through, fallback to value-listing template when a stub LLM hallucinates numbers, stage timing logging without prompt leakage, and `REFERENCE_DATE` prompt construction.
- `scripts/bench_sql.py`: Extended with `--set golden|heldout|both`, `--model`, fast-fail `/api/show` check, per-stage timing breakdown, set-level stats, and `ollama ps`.
- `docs/DATA_AND_RAG.md`, `docs/API_SPEC.md`, `docs/DECISIONS.md`: Documented `REFERENCE_DATE`, `"last N days"` convention, and summary verification rules.

---

## 4. Model Comparison (`Part D`)

| Model | Overall Match | Golden (`10`) | Held-out (`12`) | Exec OK | Mean Latency | Max Latency | `ollama ps` Split |
|---|---:|---:|---:|---:|---:|---:|---|
| `ollama/llama3.1:8b` | **18/22 (81.8%)** | **9/10** (`4/4` overlap, `5/6` novel) | **9/12** | **21/22** | **8129 ms** | **15159 ms** | `5.6 GB`, `25%/75% CPU/GPU` |
| `ollama/qwen2.5-coder:7b` | N/A | N/A | N/A | N/A | N/A | N/A | HTTP 404 (not installed) |

### Decision
- **Stopped Section D** per specification (`"If the model name is not found, paste the exact error and stop this section"`).
- Keeping **`ollama/llama3.1:8b`** as the default `LLM_MODEL` pending local pull of `qwen2.5-coder:7b` and follow-up comparison.
- Notable improvement from Parts A + B alone: `llama3.1:8b` Golden accuracy jumped from **6/10** (Phase 5, `2/6` novel) to **9/10** (`5/6` novel), plus **9/12** (`75%`) on the unseen 12-question held-out set. Held-out misses were `H01` (added extra 7-day filter + `DOW BETWEEN 6 AND 7`), `H06` (unordered month `timestamptz`), and `H09` (queried non-existent `lines_added` column on `v_commits`).

---

## 5. Gate Outputs

### 1. Security, Golden, Held-out, & Query Integration Tests
```powershell
python -m pytest tests/security tests/golden tests/integration/test_query.py -q
```
```text
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 116.60s (0:01:56)
```

### 2. Full Repository Test Suite
```powershell
python -m pytest -q
```
```text
........................................................................ [ 47%]
........................................................................ [ 94%]
.........                                                                [100%]
153 passed, 1 warning in 151.50s (0:02:31)
```

### 3. Benchmark (`both` sets) — `ollama/llama3.1:8b`
```powershell
python -m scripts.bench_sql --set both --model ollama/llama3.1:8b
```
```text
=== REAL LLM TEXT-TO-SQL BENCHMARK (set=both, count=22) ===
Model: ollama/llama3.1:8b | Prompt Reference Date: 2026-11-23
Note: Golden Q01, Q04, Q06, Q08 overlap with few-shot examples (overstate accuracy vs novel/held-out queries).

Q01 [GOLDEN OVERLAP]: What was my average sleep on days with commits > 0?
  Generated SQL : SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 10147 ms (gen=10016, val=60, exec=64)

Q02 [GOLDEN NOVEL]: What were my total commits in the last 30 days?
  Generated SQL : SELECT SUM(commits) AS total_commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 30 AND date <= CAST('2026-11-23' AS DATE) LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 7285 ms (gen=7264, val=5, exec=13)

Q03 [GOLDEN NOVEL]: Which day had the most steps?
  Generated SQL : SELECT date, steps FROM v_daily_summary ORDER BY steps DESC LIMIT 1
  Executed OK   : True | Result Match : True | Latency : 5981 ms (gen=5966, val=2, exec=11)

Q04 [GOLDEN OVERLAP]: What is the correlation between sleep_hours and commits?
  Generated SQL : SELECT ROUND(CAST(CORR(sleep_hours, commits) AS DECIMAL), 3) AS r FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 4110 ms (gen=4095, val=3, exec=11)

Q05 [GOLDEN NOVEL]: What is my average screen minutes on days sleep < 6?
  Generated SQL : SELECT ROUND(CAST(AVG(screen_minutes) AS DECIMAL), 2) AS avg_screen_minutes FROM v_daily_summary WHERE sleep_hours < 6 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 4946 ms (gen=4936, val=1, exec=8)

Q06 [GOLDEN OVERLAP]: What are my weekly commit totals?
  Generated SQL : SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary GROUP BY 1 ORDER BY 1 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 5602 ms (gen=5590, val=2, exec=8)

Q07 [GOLDEN NOVEL]: How many total pages did I read in the last 14 days?
  Generated SQL : SELECT SUM(pages_read) AS total_pages FROM v_reading WHERE date > CAST('2026-11-23' AS DATE) - 14 AND date <= CAST('2026-11-23' AS DATE) LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 8349 ms (gen=8338, val=2, exec=7)

Q08 [GOLDEN OVERLAP]: What are my top 3 screen-time categories?
  Generated SQL : SELECT category, SUM(minutes) AS total FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 3
  Executed OK   : True | Result Match : True | Latency : 8304 ms (gen=8290, val=3, exec=9)

Q09 [GOLDEN NOVEL]: What is my average HRV on days with >=1 commit compared to days with 0 commits?
  Generated SQL : SELECT ROUND(CAST(AVG(hrv_ms) FILTER(WHERE commits > 0) AS DECIMAL), 2) AS avg_hrv_commits, ROUND(CAST(AVG(hrv_ms) FILTER(WHERE commits = 0) AS DECIMAL), 2) AS avg_hrv_no_commits FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 9440 ms (gen=9411, val=9, exec=19)

Q10 [GOLDEN NOVEL]: What is my longest streak of consecutive commit days?
  Generated SQL : WITH commit_days AS (SELECT date FROM v_daily_summary WHERE commits > 0), streaks AS (SELECT date, date - CAST((ROW_NUMBER() OVER (ORDER BY date)) AS INT) AS grp FROM commit_days), longest_streak AS (SELECT MAX(streak_len) AS longest_streak FROM (SELECT COUNT(*) AS streak_len FROM streaks GROUP BY grp) AS s) SELECT (SELECT DATE_TRUNC('DAY', date) FROM commit_days ORDER BY date DESC LIMIT 1) AS longest_streak FROM longest_streak LIMIT 200
  Executed OK   : True | Result Match : False (actual=[['2026-11-23T00:00:00+00:00']] vs expected=[[16]]) | Latency : 12716 ms (gen=12670, val=11, exec=32)

H01 [HELDOUT]: How does average sleep_hours compare on weekdays versus weekends?
  Executed OK   : True | Result Match : False (actual=[[7.19, 7.6]] vs expected=[[7.37, 6.92]]) | Latency : 15159 ms (gen=15138, val=9, exec=9)

H02 [HELDOUT]: What is the median daily steps across all days?
  Executed OK   : True | Result Match : True | Latency : 7180 ms (gen=7161, val=5, exec=10)

H03 [HELDOUT]: How many days had zero commits?
  Executed OK   : True | Result Match : True | Latency : 5828 ms (gen=5813, val=2, exec=11)

H04 [HELDOUT]: What is the total lines_added between 2026-10-01 and 2026-10-31?
  Executed OK   : True | Result Match : True | Latency : 5778 ms (gen=5760, val=3, exec=13)

H05 [HELDOUT]: What is my longest streak of consecutive days with steps >= 8000?
  Executed OK   : True | Result Match : True | Latency : 10810 ms (gen=10790, val=7, exec=11)

H06 [HELDOUT]: What is my average sleep_hours grouped by month?
  Executed OK   : True | Result Match : False (actual=[['2026-11-01T00:00:00+00:00', 7.19], ...] vs expected=[['2026-08-01', 7.15], ...]) | Latency : 6331 ms (gen=6310, val=6, exec=13)

H07 [HELDOUT]: Which screen time category has the most total minutes on days with sleep_hours < 6?
  Executed OK   : True | Result Match : True | Latency : 6593 ms (gen=6581, val=3, exec=7)

H08 [HELDOUT]: What percentage of days had sleep_hours >= 7.5?
  Executed OK   : True | Result Match : True | Latency : 7873 ms (gen=7851, val=6, exec=14)

H09 [HELDOUT]: How many commits were pushed to each repository?
  Executed OK   : False ((psycopg.errors.UndefinedColumn) column "lines_added" does not exist) | Result Match : False | Latency : 11183 ms (gen=11153, val=6, exec=11)

H10 [HELDOUT]: Which book had the most total pages read?
  Executed OK   : True | Result Match : True | Latency : 8822 ms (gen=8808, val=2, exec=9)

H11 [HELDOUT]: Which day had the lowest resting_hr?
  Executed OK   : True | Result Match : True | Latency : 7452 ms (gen=7439, val=2, exec=8)

H12 [HELDOUT]: How many commits did I push in the last 14 days?
  Executed OK   : True | Result Match : True | Latency : 8939 ms (gen=8923, val=3, exec=12)

=== BENCHMARK TOTALS ===
Model                        : ollama/llama3.1:8b
Overall Executed OK          : 21/22
Overall Result Match         : 18/22
  Set 'golden'               : match=9/10, exec_ok=10/10
  Set 'heldout'               : match=9/12, exec_ok=11/12
  Golden overlap (Q1,4,6,8)  : 4/4
Latency (mean / max / total) : 8129 ms / 15159 ms / 178.83s

=== ollama ps ===
NAME           ID              SIZE      PROCESSOR          CONTEXT    RUNNER      UNTIL
llama3.1:8b    46e0c10c039e    5.6 GB    25%/75% CPU/GPU    4096       llamacpp    4 minutes from now
```

### 4. Benchmark (`both` sets) — `ollama/qwen2.5-coder:7b` (Blocked / Stopped Section D)
```powershell
python -m scripts.bench_sql --set both --model ollama/qwen2.5-coder:7b
```
```text
ERROR: Ollama model 'qwen2.5-coder:7b' not available (HTTP 404): {"error":"model 'qwen2.5-coder:7b' not found"}
```
(`ollama list` and `C:\Users\ASUS\.ollama\models\manifests` contain only `llama3.1:8b`).

### 5. Live `POST /v1/query` & Stage Timings (`X-API-Key` Masked as `***`)
```powershell
curl.exe -s -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -H "X-API-Key: ***" -d "{\"question\":\"Which day had the most steps?\"}"
```
```json
{"question":"Which day had the most steps?","standalone_question":"Which day had the most steps?","sql":"SELECT date, steps FROM v_daily_summary ORDER BY steps DESC LIMIT 1","explanation":"This query orders the daily step counts in descending order and returns the date with the highest step count.","columns":["date","steps"],"rows":[["2026-09-26",14760]],"row_count":1,"summary":"Result: date: 2026-09-26, steps: 14760.","model":"ollama/llama3.1:8b","latency_ms":7673}
```

**Observed Uvicorn Stage Timing Logs (`Part E.3`):**
```text
INFO:app.rag.embeddings:Loading embedding model sentence-transformers/all-MiniLM-L6-v2
INFO:app.main:Embedding model preloaded at startup (lifespan) in 2.591s
INFO:app.gateway.llm:Ollama call options: model=ollama/llama3.1:8b api_base=http://127.0.0.1:11434 num_ctx=4096 format=json_object temperature=0.0
INFO:app.gateway.structured:call_structured attempt=1 latency=7582.3ms output_tokens=50 validation_failed=False
INFO:app.api.routes_query:v1/query stage timings (ms): generate=7601.0 validate=42.4 execute=30.3 summarize=0.0 total=7673 ok=True
```

### 6. Lint & Secret Scan
- `ruff check` on all Phase 5.1 files: `All checks passed!`
- `git grep -nE "gh[p]_|s[k]-|AI[z]a"`: Exit 1 (0 matches)
