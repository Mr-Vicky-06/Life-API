# Phase 5.1: SQL Accuracy Hardening, Repair Path & Model Switch
Date: 2026-11-25 | Branch: phase-5-1-sql-accuracy | Status: Complete (Default switched to `ollama/qwen2.5-coder:7b`)

## 1. Objective & Scope

Completed Phase 5.1 hardening on top of initial Parts A–F before Phase 6:
- **Step 0 — Model Verification (`ollama/qwen2.5-coder:7b`)**: Verified local `qwen2.5-coder:7b` (`:3b` absent in `ollama list` -> skipped per instructions), live structured/rewrite tests, and `/health`.
- **Step 1 — Benchmark Honesty & Prompt Conventions**: Printed generated SQL & repair output for every question (`22/22`), normalized date/midnight-timestamp/decimal comparison with order-insensitive row matching unless order is asked, classified every failure `(a)/(b)/(c)`, clarified weekend/weekday `EXTRACT(DOW)` and date-filter-only-when-asked rules, tracked `[HELDOUT TUNED]` (`H01, H08, H09`) separately from `[HELDOUT UNTUNED]` (`9` questions), and documented all pattern overlaps across both suites.
- **Step 2 — Column-Aware One-Shot SQL Repair**: Updated `repair_sql` to inject exact PostgreSQL column lists (`format_view_columns_for_sql`) for every view referenced in the failed query alongside the sanitized DB error; verified with a stubbed hallucinated-column integration test and observed live repairs on `H09`, `Q07`, and `H12`.
- **Step 3 — Latency Measurements & Optimizations**: Measured KV prefix reordering (`3a`), 15-word `explanation` cap (`3b`), top-level Ollama `keep_alive=30m` via LiteLLM `extra_body` (`3c`), and `num_ctx=3072` (`3d`). Kept winners `3a+3b+3c`; dropped `3d` (`num_ctx=3072` regressed latency).
- **Step 4 — Model Evaluation & Default Switch**: Benchmarked `ollama/qwen2.5-coder:7b` (`21/22` overall, `9/10` golden, `12/12` held-out, `9/9` untuned held-out, `4301 ms` mean) against the rough pre-edit `ollama/llama3.1:8b` baseline (`18/22`, `9/10` golden, `9/12` held-out, `8129 ms` mean) and updated default `LLM_MODEL` to `ollama/qwen2.5-coder:7b`.
- **Step 5 — Limits**: Confirmed `Q10` (`longest streak of consecutive commit days`) passes cleanly (`4701 ms`); documented remaining `Q06` `(a)` date-filter failure without special-casing.

---

## 2. Part A: Reference Date Proof & Convention (Preserved)

Computed Q02 (`"total commits in the last 30 days"`) under both anchors on the fixed seed ending `2026-11-23`:
```text
Anchor 2026-11-23 (anchor-30 = 2026-10-24):
  date > anchor - 30  (30d inclusive window) : 116 (unbounded upper: 116)
  date >= anchor - 30 (31d window if <=anchor): 119
Anchor 2026-11-25 (anchor-30 = 2026-10-26):
  date > anchor - 30  (30d inclusive window) : 104 (unbounded upper: 104)
  date >= anchor - 30 (31d window if <=anchor): 115
```
`REFERENCE_DATE` defaults to today in `APP_TIMEZONE` in production and is pinned to `SEED_END_DATE=2026-11-23` in `bench_sql.py` and golden tests.

---

## 3. Step 0: Ollama Model Check (`qwen2.5-coder:7b`)

```text
NAME                ID              SIZE      MODIFIED
qwen2.5-coder:7b    dae161e27b0e    4.7 GB    4 minutes ago
```
(`qwen2.5-coder:3b` is not installed -> skipped cleanly.)

Initial `pytest -m live -q -W ignore`: `3 passed, 150 deselected in 86.88s` (`attempt=1`, `validation_failed=False`). Final post-edit run: `3 passed, 150 deselected in 39.83s`.
Live `GET /health`: `{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"none"}`.

---

## 4. Step 1: Failure Classification, Tuned Split & Pattern Overlap

### Pre-Tuning Failures on `qwen2.5-coder:7b` (`17/22`: Golden `8/10`, Held-out `9/12`, Untuned `9/9`)
| QID | Classification | Observed Failure & SQL | Action Taken |
|---|---|---|---|
| `Q06` | **(a) Model SQL error** | Added spurious `WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE)` to `"What are my weekly commit totals?"` (`[['2026-11-16', 26.0], ['2026-11-23', 1.0]]` vs 14 weeks). | Moved `'last N days'` rule out of `build_date_context()` into static prefix and added explicit "date WHERE filter ONLY when asked" rule. |
| `Q08` | **(a) Model SQL error** | Added spurious `WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE)` (`Productivity=1631` vs `21324`). | Fixed by date-filter-only-when-asked rule & cleaner `build_date_context()`. |
| `H01` | **(c) Ambiguous question** | Wrote `EXTRACT(DOW FROM date) < 5` vs `>= 5` (`[[7.27, 7.17]]` vs `[[7.37, 6.92]]`). PostgreSQL `DOW` is `0=Sun..6=Sat`, not Python `0..4`. | Added PostgreSQL weekend/weekday convention (`IN (0, 6)` vs `BETWEEN 1 AND 5`) to `schema_prompt.py`. |
| `H08` | **(a) Model SQL error** | Added spurious `WHERE date > CAST('2026-11-23' AS DATE) - 7` (`[[42.86]]` vs `[[43.33]]`). | Fixed by cleaner `build_date_context()` + negative constraint. |
| `H09` | **(a) Model SQL error** | Added spurious `- 7` filter + `LIMIT 5` (`[['voicecore', 17], ['Life-API', 10]]` vs `[['Life-API', 199], ['voicecore', 199]]`), though `repair_sql` fixed `date` -> `commit_date`. | Fixed by date-filter & omit-unasked-`LIMIT` rule in `schema_prompt.py`. |

### Post-Tuning Remaining Failure (`21/22`: Golden `9/10`, Held-out `12/12`, Untuned `9/9`)
- **`Q06` (`(a)` Model SQL error)**: Generated `SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE) GROUP BY 1 ORDER BY 1 LIMIT 200` (`actual=[['2026-11-16', 26.0], ['2026-11-23', 1.0]]` vs 14 weekly rows). The model still copied `- 7` from the adjacent relative-window few-shot example despite the negative rule.

### Pattern Overlap Analysis (`Step 1e`)
Which Golden and Held-out questions share a structural SQL pattern with the 8 few-shot examples in `app/sql_agent/schema_prompt.py`:
- **Filtered scalar aggregate (`avg/count ... WHERE`)**: `Q01` (literal overlap), `Q05` (`sleep_hours < 6`), `H03` (`COUNT(*) WHERE commits = 0`).
- **Relative window (`date > ref - N AND date <= ref`)**: `Q02` (30 days), `Q07` (14 days), `H12` (14 days).
- **Correlation (`corr`)**: `Q04` (literal overlap).
- **Period bucketing (`date_trunc` + `GROUP BY 1 ORDER BY 1`)**: `Q06` (literal overlap, weekly), `H06` (monthly `sleep_hours`).
- **Grouped sum / Top-N (`GROUP BY ... ORDER BY ... DESC LIMIT N`)**: `Q08` (literal overlap, `LIMIT 3`), `H07` (`LIMIT 1` with `v_daily_summary` subquery), `H09` (per-repo `v_commits`), `H10` (`v_reading` top book).
- **Argmax / Argmin row (`ORDER BY col DESC/ASC LIMIT 1`)**: `Q03` (max `steps`), `H11` (min `resting_hr`).
- **Conditional aggregation (`FILTER (WHERE ...)`)**: `Q09` (HRV `>=1` vs `0` commits), `H01` (weekday vs weekend sleep), `H08` (percentage `sleep_hours >= 7.5` via `COUNT(*) FILTER`).
- **Gaps-and-islands streak (`date - row_number()`)**: `Q10` (`commits > 0`), `H05` (`steps >= 8000`).
- **No matching few-shot SQL example (1-line syntax hint or general SQL)**: `H02` (`percentile_cont(0.5) WITHIN GROUP`), `H04` (`BETWEEN` fixed date range).

---

## 5. Step 2: Column-Aware Repair Path

- `VIEW_COLUMNS` + `format_view_columns_for_sql(sql)` in `app/sql_agent/schema_prompt.py` extracts exact columns for referenced views (`v_daily_summary`, `v_commits`, `v_screen_time`, `v_reading`).
- `repair_sql()` in `app/sql_agent/generator.py` supplies `failed_sql`, `error_text[:600]`, and `format_view_columns_for_sql(failed_sql)`. `app/api/routes_query.py` logs sanitized `err_snippet` without prompt text.
- **Test verification**: `test_query_repair_path_succeeds_once` (`tests/integration/test_query.py`) stubs a hallucinated column (`sum(lines_added) FROM v_commits`), asserts `v_commits:` column list appears in the repair prompt, and passes end-to-end.
- **Real Ollama repairs observed in final benchmark**:
  - `Q07`: `GroupingError` (`ORDER BY date` with `SUM(pages_read)`) -> repaired cleanly to remove `ORDER BY date`.
  - `H09`: `UndefinedColumn` (`column "date" does not exist` on `v_commits`) -> repaired cleanly to `commit_date`.
  - `H12`: `GroupingError` (`ORDER BY date` with `SUM(commits)`) -> repaired cleanly to remove `ORDER BY date`.

---

## 6. Step 3: Warm SQL-Generation Latency Optimizations (`qwen2.5-coder:7b`, 5-question microbench)

| Variant | Mean Gen (ms) | Mean Prompt Eval (ms) | Mean Out Tokens | Mean Expl Words | `ollama ps` Split / Expiry | Decision |
|---|---:|---:|---:|---:|---|---|
| Baseline (`num_ctx=4096`, date at top, unbounded expl, default `keep_alive`) | 4599 | 272.9 | 76.4 | 30.2 | `18%/82% CPU/GPU`, `UNTIL 4 min` | Baseline |
| **3a** Static prefix first, date+question last | 4694 | **202.2 (-25.9%)** | 86.0 | 24.4 | `18%/82% CPU/GPU` | **Keep** |
| **3a+3b** + `explanation` max 15 words | 4250 | **154.8** | 75.8 | **10.6** | `18%/82% CPU/GPU` | **Keep** |
| **3a+3b+3c** + `keep_alive="30m"` (`extra_body`) | **4131** | 180.4 | **69.0** | **10.2** | `18%/82% CPU/GPU`, **`UNTIL 29 min`** | **Keep** |
| **3a+3b+3c+3d** + `num_ctx=3072` | 4935 | 222.6 | 69.0 | 10.2 | **`19%/81% CPU/GPU`** | **Drop** (slower & worse GPU%) |

*Note:* LiteLLM's `ollama/` handler places unknown kwargs inside `"options"`, where Ollama ignored `keep_alive`; passing `extra_body={"keep_alive": cfg.llm_keep_alive}` in `app/gateway/llm.py` sends `keep_alive` at top level and verified `UNTIL 29 minutes from now` in `ollama ps`.

---

## 7. Step 4: Model Comparison & Switching Decision

> **Baseline caveat:** `ollama/llama3.1:8b` was removed from local Ollama before this step, so its figures (`reports/phase-5-1-sql-accuracy.md` pre-edit run) were measured **before** Step 1–3 prompt, repair, and harness changes and serve as a **rough baseline**. `qwen2.5-coder:3b` was absent and skipped.

| Run | Model | Overall Match | Golden (`10`) | Held-out Total (`12`) | Held-out Untuned (`9`) | Exec OK | Mean / Max / Total |
|---|---|---:|---:|---:|---:|---:|---|
| Rough Baseline (pre-Step 1–3) | `ollama/llama3.1:8b` | 18/22 (81.8%) | 9/10 (`4/4` overlap) | 9/12 | — | 21/22 | 8129 ms / 15159 ms / 178.83s |
| Pre-Tuning 1c | `ollama/qwen2.5-coder:7b` | 17/22 (77.3%) | 8/10 (`2/4` overlap) | 9/12 | **9/9 (100%)** | **22/22** | 5423 ms / 21544 ms / 119.31s (`mean_gen=5388 ms`) |
| **Final Post-Tuning** | **`ollama/qwen2.5-coder:7b`** | **21/22 (95.5%)** | **9/10 (`3/4` overlap)** | **12/12 (100%)** | **9/9 (100%)** | **22/22** | **4301 ms / 10161 ms / 94.62s (`mean_gen=4264 ms`)** |

**Decision:** Live structured tests pass and untuned held-out accuracy (`9/9`) beats baseline (`>= baseline - 2` threshold), with `+3` overall accuracy (`21/22` vs `18/22`) and ~47% faster mean latency (`4.3s` vs `8.1s`). Switched default `LLM_MODEL` to `ollama/qwen2.5-coder:7b` in `app/config.py`, `.env.example`, `docs/ARCHITECTURE.md`, `README.md`, and `tests/test_health.py`.

---

## 8. Complete 22-Question Benchmark Output (`ollama/qwen2.5-coder:7b`, Final)

```powershell
python -m scripts.bench_sql --set both
```
```text
=== REAL LLM TEXT-TO-SQL BENCHMARK (set=both, count=22) ===
Model: ollama/qwen2.5-coder:7b | Prompt Reference Date: 2026-11-23
Note: Golden Q01, Q04, Q06, Q08 overlap with few-shot examples (overstate accuracy vs novel/held-out queries).

Q01 [GOLDEN OVERLAP]: What was my average sleep on days with commits > 0?
  Generated SQL : SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 6313 ms (gen=6156, val=83, exec=69)

Q02 [GOLDEN NOVEL]: What were my total commits in the last 30 days?
  Generated SQL : SELECT SUM(commits) AS total_commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 30 AND date <= CAST('2026-11-23' AS DATE) LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 3793 ms (gen=3771, val=6, exec=13)

Q03 [GOLDEN NOVEL]: Which day had the most steps?
  Generated SQL : SELECT date, steps FROM v_daily_summary WHERE steps > 0 ORDER BY steps DESC LIMIT 1
  Executed OK   : True | Result Match : True | Latency : 2357 ms (gen=2336, val=6, exec=13)

Q04 [GOLDEN OVERLAP]: What is the correlation between sleep_hours and commits?
  Generated SQL : SELECT ROUND(CAST(CORR(sleep_hours, commits) AS DECIMAL), 3) AS r FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 2325 ms (gen=2306, val=5, exec=10)

Q05 [GOLDEN NOVEL]: What is my average screen minutes on days sleep < 6?
  Generated SQL : SELECT ROUND(CAST(AVG(screen_minutes) AS DECIMAL), 2) AS avg_screen FROM v_daily_summary WHERE sleep_hours < 6 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 2668 ms (gen=2642, val=5, exec=18)

Q06 [GOLDEN OVERLAP]: What are my weekly commit totals?
  Generated SQL : SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE) GROUP BY 1 ORDER BY 1 LIMIT 200
  Executed OK   : True | Result Match : False (actual=[['2026-11-16', 26.0], ['2026-11-23', 1.0]] vs expected=[['2026-08-24', 17], ['2026-08-31', 42], ['2026-09-07', 21]])
  Latency       : 5195 ms (gen=5174, val=5, exec=10)

Q07 [GOLDEN NOVEL]: How many total pages did I read in the last 14 days?
  Generated SQL : SELECT SUM(pages_read) AS total_pages FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 14 AND date <= CAST('2026-11-23' AS DATE) ORDER BY date LIMIT 200
  Repair Trigger: (psycopg.errors.GroupingError) column "v_daily_summary.date" must appear in the GROUP BY clause or be used in an aggregate function
  Repaired SQL  : SELECT SUM(pages_read) AS total_pages FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 14 AND date <= CAST('2026-11-23' AS DATE) LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 10161 ms (gen=10110, val=15, exec=32)

Q08 [GOLDEN OVERLAP]: What are my top 3 screen-time categories?
  Generated SQL : SELECT category, SUM(minutes) AS total FROM v_screen_time WHERE date <= CAST('2026-11-23' AS DATE) GROUP BY 1 ORDER BY 2 DESC LIMIT 3
  Executed OK   : True | Result Match : True | Latency : 3285 ms (gen=3267, val=5, exec=10)

Q09 [GOLDEN NOVEL]: What is my average HRV on days with >=1 commit compared to days with 0 commits?
  Generated SQL : SELECT ROUND(CAST(AVG(hrv_ms) FILTER(WHERE commits > 0) AS DECIMAL), 2) AS high_commit_hrv, ROUND(CAST(AVG(hrv_ms) FILTER(WHERE commits = 0) AS DECIMAL), 2) AS no_commit_hrv FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 4278 ms (gen=4237, val=14, exec=23)

Q10 [GOLDEN NOVEL]: What is my longest streak of consecutive commit days?
  Generated SQL : WITH commit_streaks AS (SELECT date, date - CAST((ROW_NUMBER() OVER (ORDER BY date)) AS INT) AS grp FROM v_daily_summary WHERE commits > 0) SELECT COALESCE(MAX(streak_len), 0) AS longest_streak FROM (SELECT COUNT(*) AS streak_len FROM commit_streaks GROUP BY grp) AS streaks LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 4701 ms (gen=4677, val=11, exec=11)

H01 [HELDOUT TUNED]: How does average sleep_hours compare on weekdays versus weekends?
  Generated SQL : SELECT ROUND(CAST(AVG(sleep_hours) FILTER(WHERE EXTRACT(DOW FROM date) BETWEEN 1 AND 5) AS DECIMAL), 2) AS avg_weekday_sleep, ROUND(CAST(AVG(sleep_hours) FILTER(WHERE EXTRACT(DOW FROM date) IN (0, 6)) AS DECIMAL), 2) AS avg_weekend_sleep FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 4699 ms (gen=4668, val=9, exec=20)

H02 [HELDOUT UNTUNED]: What is the median daily steps across all days?
  Generated SQL : SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY steps) AS median_steps FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 2371 ms (gen=2351, val=5, exec=14)

H03 [HELDOUT UNTUNED]: How many days had zero commits?
  Generated SQL : SELECT COUNT(*) AS days_with_zero_commits FROM v_daily_summary WHERE commits = 0 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 2388 ms (gen=2337, val=3, exec=40)

H04 [HELDOUT UNTUNED]: What is the total lines_added between 2026-10-01 and 2026-10-31?
  Generated SQL : SELECT SUM(lines_added) AS total_lines_added FROM v_daily_summary WHERE date BETWEEN '2026-10-01' AND '2026-10-31' LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 3280 ms (gen=3243, val=6, exec=29)

H05 [HELDOUT UNTUNED]: What is my longest streak of consecutive days with steps >= 8000?
  Generated SQL : WITH active_days AS (SELECT date, date - CAST((ROW_NUMBER() OVER (ORDER BY date)) AS INT) AS grp FROM v_daily_summary WHERE steps >= 8000), streaks AS (SELECT COUNT(*) AS streak_len FROM active_days GROUP BY grp) SELECT COALESCE(MAX(streak_len), 0) AS longest_streak FROM streaks LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 5189 ms (gen=5141, val=21, exec=24)

H06 [HELDOUT UNTUNED]: What is my average sleep_hours grouped by month?
  Generated SQL : SELECT CAST(DATE_TRUNC('MONTH', date) AS DATE) AS month, AVG(sleep_hours) AS avg_sleep FROM v_daily_summary GROUP BY 1 ORDER BY 1 LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 5073 ms (gen=5055, val=6, exec=9)

H07 [HELDOUT UNTUNED]: Which screen time category has the most total minutes on days with sleep_hours < 6?
  Generated SQL : SELECT category, SUM(minutes) AS total FROM v_screen_time WHERE date IN (SELECT date FROM v_daily_summary WHERE sleep_hours < 6) GROUP BY category ORDER BY total DESC LIMIT 1
  Executed OK   : True | Result Match : True | Latency : 3593 ms (gen=3570, val=4, exec=15)

H08 [HELDOUT TUNED]: What percentage of days had sleep_hours >= 7.5?
  Generated SQL : SELECT ROUND(CAST((COUNT(*) FILTER(WHERE sleep_hours >= 7.5) * 100.0 / COUNT(*)) AS DECIMAL), 2) AS percentage FROM v_daily_summary LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 3402 ms (gen=3353, val=10, exec=35)

H09 [HELDOUT TUNED]: How many commits were pushed to each repository?
  Generated SQL : SELECT repo, COUNT(*) AS commits FROM v_commits WHERE date <= CAST('2026-11-23' AS DATE) GROUP BY repo ORDER BY commits DESC LIMIT 200
  Repair Trigger: (psycopg.errors.UndefinedColumn) column "date" does not exist
  Repaired SQL  : SELECT repo, COUNT(*) AS commits FROM v_commits WHERE commit_date <= CAST('2026-11-23' AS DATE) GROUP BY repo ORDER BY commits DESC LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 6723 ms (gen=6670, val=14, exec=37)

H10 [HELDOUT UNTUNED]: Which book had the most total pages read?
  Generated SQL : SELECT title, SUM(pages_read) AS total_pages FROM v_reading GROUP BY title ORDER BY total_pages DESC LIMIT 1
  Executed OK   : True | Result Match : True | Latency : 2650 ms (gen=2631, val=5, exec=10)

H11 [HELDOUT UNTUNED]: Which day had the lowest resting_hr?
  Generated SQL : SELECT date, resting_hr FROM v_daily_summary WHERE resting_hr > 0 ORDER BY resting_hr ASC LIMIT 1
  Executed OK   : True | Result Match : True | Latency : 2523 ms (gen=2504, val=3, exec=14)

H12 [HELDOUT UNTUNED]: How many commits did I push in the last 14 days?
  Generated SQL : SELECT SUM(commits) AS total_commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 14 AND date <= CAST('2026-11-23' AS DATE) ORDER BY date LIMIT 200
  Repair Trigger: (psycopg.errors.GroupingError) column "v_daily_summary.date" must appear in the GROUP BY clause or be used in an aggregate function
  Repaired SQL  : SELECT SUM(commits) AS total_commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 14 AND date <= CAST('2026-11-23' AS DATE) LIMIT 200
  Executed OK   : True | Result Match : True | Latency : 7658 ms (gen=7606, val=11, exec=37)

=== BENCHMARK TOTALS ===
Model                        : ollama/qwen2.5-coder:7b
Overall Executed OK          : 22/22
Overall Result Match         : 21/22
  Set 'golden'               : match=9/10, exec_ok=10/10
  Set 'heldout'              : match=12/12, exec_ok=12/12
  Golden overlap (Q1,4,6,8)  : 3/4
  Held-out untuned           : 9/9
  Held-out tuned (H01,08,09) : 3/3
Latency (mean / max / total) : 4301 ms / 10161 ms / 94.62s (mean_gen=4264 ms)

=== ollama ps ===
NAME                ID              SIZE      PROCESSOR          CONTEXT    RUNNER      UNTIL
qwen2.5-coder:7b    dae161e27b0e    5.2 GB    18%/82% CPU/GPU    4096       llamacpp    29 minutes from now
```

---

## 9. Final Gate & Live Verification Outputs

### 1. Security, Golden, Held-out & Query Integration
```powershell
python -m pytest tests/security tests/golden tests/integration/test_query.py -q
```
```text
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 45.81s
```

### 2. Full Non-Live Test Suite
```powershell
python -m pytest -q
```
```text
........................................................................ [ 47%]
........................................................................ [ 94%]
.........                                                                [100%]
153 passed, 1 warning in 66.20s (0:01:06)
```

### 3. Live Ollama Suite
```powershell
python -m pytest -m live -q -W ignore
```
```text
...                                                                      [100%]
3 passed, 150 deselected in 39.83s
```

### 4. Live API Check (`GET /health` & `POST /v1/query`, `X-API-Key` Masked as `***`)
- `GET /health`: `{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"none"}`
- `POST /v1/query` (`{"question":"Which day had the most steps?"}`):
```json
{"question":"Which day had the most steps?","standalone_question":"Which day had the most steps?","sql":"SELECT date, steps FROM v_daily_summary WHERE steps > 0 ORDER BY steps DESC LIMIT 1","explanation":"Find the day with the highest number of steps.","columns":["date","steps"],"rows":[["2026-09-26",14760]],"row_count":1,"summary":"Result: date: 2026-09-26, steps: 14760.","model":"ollama/qwen2.5-coder:7b","latency_ms":5322}
```
- Uvicorn logs (`v1/query` stage timings, no prompt content logged):
```text
INFO:app.gateway.llm:Ollama call options: model=ollama/qwen2.5-coder:7b api_base=http://127.0.0.1:11434 num_ctx=4096 keep_alive=30m format=json_object temperature=0.0
INFO:app.gateway.structured:call_structured attempt=1 latency=5285.2ms output_tokens=45 validation_failed=False
INFO:app.api.routes_query:v1/query stage timings (ms): generate=5293.4 validate=18.3 execute=10.8 summarize=0.0 total=5322 ok=True
Port 8000 listeners after stop: 0
```

### 5. Lint & Secret Scan
- `python -m ruff check app/config.py app/gateway/llm.py app/sql_agent/ app/api/routes_query.py scripts/bench_sql.py tests/integration/test_query.py tests/unit/test_summary.py tests/test_health.py tests/golden/`: `All checks passed!`
- `git grep -nE "gh[p]_|s[k]-|AI[z]a"`: Exit 1 (`0` matches; clean).
