# Phase 5: Text-to-SQL (plus Step 0 Seed, API Key, & Latency Fixes)
Date: 2026-11-25 | Branch: phase-5-text-to-sql | Status: Passed

## 1. Objective

1. **Step 0A — Fix Seed Duplication & Contradictory Journal Copy**:
   Diagnose why duplicate/contradictory journal notes appeared in Phase 4 search results, anchor seed dates to a fixed `SEED_END_DATE` (default `2026-11-23`), add `python -m scripts.seed --reset` (restricted to `APP_ENV=dev`), align journal narratives with daily metrics without `"Day N"` drift, and guarantee at most 1 journal note per date.
2. **Step 0B — Enforce Non-Default API Key Security**:
   Generate a random 43-character key into `.env` (never printed), keep `change-me` strictly in `.env.example`, refuse app startup when `APP_ENV != "dev"` and the API key is default/empty, and scrub any literal key values in `reports/` to `***`.
3. **Step 0C — Measure Ollama Options & Live Latency Breakdown**:
   Verify actual HTTP request options sent to Ollama (`num_ctx=4096`, `format`, `temperature`), measure 3 consecutive `call_structured` calls with latency and tokens/s alongside `ollama ps`, and separate test collection/import overhead from live test execution in `pytest -m live`.
4. **Phase 5 — Build Text-to-SQL Pipeline (`app/sql_agent/` + `POST /v1/query`)**:
   - View-only schema prompt (`schema_prompt.py`) exposing only the 4 allowlisted views, column metadata, 5 few-shot examples, and current date in `APP_TIMEZONE`.
   - Structured SQL generation & 1-shot error repair (`generator.py`).
   - Strict `sqlglot` AST + tokenizer validator (`validator.py`) enforcing single `SELECT`, view allowlist, no blocked/`pg_*` functions, comment/keyword checks, no schema qualifiers/system catalogs, and `LIMIT 200` enforcement/clamping.
   - Read-only SQL executor (`executor.py`) running on `life_ro` with `SET LOCAL statement_timeout = '5s'` and JSON-safe row serialization.
   - Authenticated `POST /v1/query` endpoint (`routes_query.py`) implementing `check_input -> rewrite -> generate -> validate -> execute (+1 repair) -> summarize (<data> + check_output)` plus persistent `query_log` auditing via RW engine on both success and failures.

---

## 2. Step 0 Diagnostics & Fixes

### Step 0A: Seed Duplication & Contradiction Evidence (Before Fix)

Queries run against the pre-fix `life` database confirmed both suspected root causes:

```text
 count |    min     |    max     | span_days
-------+------------+------------+-----------
    91 | 2026-08-26 | 2026-11-24 |        90

 source_type  | count
--------------+-------
 reading_note |    50
 journal      |   141

 note_date  | count
------------+-------
 2026-08-27 |     2
 ...
 2026-10-05 |     2
 2026-10-06 |     3

 sleep_commit_corr
-------------------
            0.3944
```

- **Confirmed Cause 1 (Date-shift via `date.today()`)**: Running on Nov 23 vs Nov 24 shifted the 90-day window from `2026-08-26..2026-11-23` to `2026-08-27..2026-11-24` (91 rows in `health_daily`, 90-day span). `day_offset=40` (`"Day 41"`, `5.79h` sleep) shifted from `2026-10-05` (`id=175`) to `2026-10-06` (`id=247`), colliding with `2026-10-06`'s earlier `"Day 42"` notes (`id=32`, `id=176`) and creating extra `github_commits` whose SHA included `current_date`, pulling `corr(sleep_hours, commits)` down to `0.3944`.
- **Confirmed Cause 2 (`content_hash` + Static Prompts Ignoring Sleep)**: Updated journal formatting in Phase 4 generated a new `content_hash` on identical dates (`id=7` vs `id=151` on `2026-09-04`), retaining prior rows alongside new ones. Meanwhile, cycling through `JOURNAL_PROMPTS[journal_idx % 15]` emitted `"Woke up feeling well-rested after 8 hours of sleep..."` alongside `"Recorded sleep was 5.79 hours ... Slept badly last night"`.

#### Post-Fix Seed `--reset` and Idempotency Output

```powershell
python -m scripts.seed --reset
docker compose exec -T db psql -P pager=off -U life -d life -c "SELECT (SELECT count(*) FROM health_daily) AS health, (SELECT count(*) FROM github_commits) AS commits, (SELECT count(*) FROM reading_log) AS reading, (SELECT count(*) FROM screen_time) AS screen, (SELECT count(*) FROM notes) AS notes, (SELECT count(*) FROM note_chunks) AS chunks;"

python -m scripts.seed
docker compose exec -T db psql -P pager=off -U life -d life -c "SELECT (SELECT count(*) FROM health_daily) AS health, (SELECT count(*) FROM github_commits) AS commits, (SELECT count(*) FROM reading_log) AS reading, (SELECT count(*) FROM screen_time) AS screen, (SELECT count(*) FROM notes) AS notes, (SELECT count(*) FROM note_chunks) AS chunks;"
```

```text
Seed completed: health=90ins/0upd, commits=398ins/0upd, reading=68ins/0upd, screen=270ins/0upd, notes=72ins/0skip
 health | commits | reading | screen | notes | chunks
--------+---------+---------+--------+-------+--------
     90 |     398 |      68 |    270 |    72 |     72

Seed completed: health=0ins/90upd, commits=0ins/398upd, reading=0ins/68upd, screen=0ins/270upd, notes=0ins/72skip
 health | commits | reading | screen | notes | chunks
--------+---------+---------+--------+-------+--------
     90 |     398 |      68 |    270 |    72 |     72
```

**Verification Queries (`life` DB):**
```text
 count |    min     |    max     | span_days
-------+------------+------------+-----------
    90 | 2026-08-26 | 2026-11-23 |        89

-- Journal dates with count > 1:
(0 rows)

 source_type  | count
--------------+-------
 reading_note |    25
 journal      |    47

 sleep_commits_corr
--------------------
             0.6989

-- Contradictory wording / "Day N" check:
 contradictory_day_or_rested
-----------------------------
                           0
```

### Step 0B: API Key Hardening

- Generated a 43-character random URL-safe key directly into local `.env` without printing it; retained `APP_API_KEY=change-me` strictly in `.env.example`.
- Added `validate_startup_security(settings)` to `app/config.py` (enforced via `@model_validator` and FastAPI startup/lifespan). Starting with `APP_ENV=prod` and `APP_API_KEY=change-me` immediately raises `ValidationError: Refusing to start: APP_API_KEY must be changed from the default when APP_ENV is not 'dev'`.
- Replaced `change-me` in `reports/phase-4-search.md` with `***`. `git grep -n "change-me" reports/` returns 0 matches.

### Step 0C: Ollama Options & Latency Measurement

1. **HTTP Payload Inspection & Logged Options**:
   LiteLLM sends `"options": {"num_ctx": 4096}`, `"stream": false`, `"format": "json"` to `http://127.0.0.1:11434/api/generate`. `app/gateway/llm.py` logs:
   ```text
   Ollama call options: model=ollama/llama3.1:8b api_base=http://127.0.0.1:11434 num_ctx=4096 format=json_object temperature=0.0
   ```
2. **Three Consecutive `call_structured` Runs + `ollama ps`** (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`):
   ```text
   Run 1: latency=3.845s | output_tokens=10 | tokens_per_s=2.6 tok/s
   Run 2: latency=0.680s | output_tokens=10 | tokens_per_s=14.7 tok/s
   Run 3: latency=0.670s | output_tokens=10 | tokens_per_s=14.9 tok/s
   ```
   ```text
   NAME           ID              SIZE      PROCESSOR          CONTEXT    RUNNER      UNTIL
   llama3.1:8b    46e0c10c039e    5.6 GB    25%/75% CPU/GPU    4096       llamacpp    4 minutes from now
   ```
   Flash attention + Q8 KV cache reduced memory footprint from 6.8 GB to 5.6 GB and kept warm `call_structured` latency at **0.67–0.68 s** (well under the 5 s target). Note: Run 1 in a fresh Python process is slower (~3.8s when Ollama is warm, or >60s on cold weight load) in part because LiteLLM also performs initial `/api/show` metadata calls to `http://localhost:11434/api/show` before caching.
3. **`pytest -m live -q --durations=5 -W ignore` vs Collection/Import Overhead**:
   ```text
   ..                                                                       [100%]
   ============================= slowest 5 durations =============================
   5.32s call     tests/test_live_rewrite.py::test_live_ollama_query_rewrite
   2.38s call     tests/test_live_structured.py::test_live_ollama_call_structured

   (3 durations < 0.005s hidden.  Use -vv to show these durations.)
   2 passed, 72 deselected in 38.31s
   ```
   Measured `--collect-only -m live -q -W ignore`: `2/74 tests collected (72 deselected) in 23.19s` (`27.72s` wall clock including Python/pytest boot). Separating the phases proves only **7.70 s** is live LLM test execution (`5.32s + 2.38s`), while **~30.6 s** inside the pytest session (and `45.27s` total wall clock) is Python/pytest startup plus importing `torch`, `sentence_transformers`, `litellm`, and `sqlalchemy` during 74-test collection on Windows.

---

## 3. What Was Built (Phase 5)

- `app/schemas/query.py`: `QueryRequest` and `QueryResponse` Pydantic v2 models matching `docs/API_SPEC.md`.
- `app/gateway/exceptions.py`: Added `SQLRejected` (`422`, `sql_rejected`) and `SQLFailed` (`422`, `sql_failed`).
- `app/sql_agent/schema_prompt.py`: Prompt built strictly from the 4 allowlisted views (`v_daily_summary`, `v_commits`, `v_screen_time`, `v_reading`), column types/descriptions, 5 few-shot examples from `DATA_AND_RAG.md`, and today's date in `APP_TIMEZONE` — zero base table references.
- `app/sql_agent/validator.py`: `sqlglot` (`postgres`) validator checking comments & tokens (`;`, `INTO`, `FOR UPDATE`, `LOCK`), single `exp.Select` root (CTEs allowed), zero mutating AST nodes inside CTEs/subqueries, strict view allowlist with no schema qualifiers or system catalogs (`information_schema`, `pg_catalog`), blocked/`pg_*` functions, and `LIMIT 200` default/clamping (including `FETCH FIRST`).
- `app/sql_agent/generator.py`: `GeneratedSQL` structured generation and one-shot `repair_sql` feedback loop.
- `app/sql_agent/executor.py`: Executes validated SQL via `ro_engine()` inside a `READ ONLY` transaction with `SET LOCAL statement_timeout = '5000ms'`, returning max 200 JSON-safe rows (`Decimal` -> `float`, `date`/`datetime` -> ISO strings).
- `app/api/routes_query.py`: Authenticated `POST /v1/query` endpoint running `check_input -> rewrite -> generate -> validate -> execute (+1 repair) -> summarize (<data> + check_output)` and logging every request (masked question, sql, latency_ms, model, ok, error) to `query_log` via `rw_engine()`.
- `app/main.py`: Registered `query_router` and `validate_startup_security` checks.
- `tests/security/test_sql_validator.py`, `tests/security/test_ro_executor.py`, `tests/security/test_startup_security.py`, `tests/golden/test_golden_sql.py`, `tests/integration/test_query.py`, `tests/test_live_sql.py`, and `scripts/bench_sql.py`.

---

## 4. Gate Results

### 1. Security, Golden SQL, & Query Integration Tests
```powershell
python -m pytest tests/security tests/golden tests/integration/test_query.py -q
```
```text
........................................................................ [ 96%]
...                                                                      [100%]
75 passed in 59.29s
```

### 2. Full Repository Test Suite
```powershell
python -m pytest -q
```
```text
........................................................................ [ 53%]
...............................................................          [100%]
135 passed, 1 warning in 119.06s (0:01:59)
```

### 3. Real LLM SQL Benchmark (`scripts/bench_sql.py` — not a gate)
```powershell
python -m scripts.bench_sql
```
```text
=== REAL LLM TEXT-TO-SQL BENCHMARK (10 GOLDEN QUESTIONS) ===
Model: ollama/llama3.1:8b | Schema prompt ref date: 2026-11-25
Note: Questions Q1, Q4, Q6, Q8 overlap with few-shot examples in schema_prompt.py (overstate accuracy).

Q01 [FEW-SHOT OVERLAP]: What was my average sleep on days with commits > 0?
  Generated SQL : SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200
  Executed OK   : True
  Result Match  : True
  Latency       : 10140 ms

Q02 [NOVEL]: What were my total commits in the last 30 days?
  Generated SQL : SELECT SUM(commits) AS total_commits FROM v_daily_summary WHERE date >= CURRENT_DATE - 30 LIMIT 200
  Executed OK   : True
  Result Match  : False (actual=[[115.0]] vs expected=[[116]])
  Latency       : 5540 ms

Q03 [NOVEL]: Which day had the most steps?
  Generated SQL : SELECT date, MAX(steps) AS max_steps FROM v_daily_summary GROUP BY 1 LIMIT 200
  Executed OK   : True
  Result Match  : False (actual=[['2026-09-12', 6267], ['2026-09-27', 7744]] vs expected=[['2026-09-26', 14760]])
  Latency       : 6698 ms

Q04 [FEW-SHOT OVERLAP]: What is the correlation between sleep_hours and commits?
  Generated SQL : SELECT ROUND(CAST(CORR(sleep_hours, commits) AS DECIMAL), 3) AS r FROM v_daily_summary LIMIT 200
  Executed OK   : True
  Result Match  : True
  Latency       : 4266 ms

Q05 [NOVEL]: What is my average screen minutes on days sleep < 6?
  Generated SQL : SELECT ROUND(CAST(AVG(screen_minutes) AS DECIMAL), 2) AS avg_screen_minutes FROM v_daily_summary WHERE sleep_hours < 6 LIMIT 200
  Executed OK   : True
  Result Match  : True
  Latency       : 5832 ms

Q06 [FEW-SHOT OVERLAP]: What are my weekly commit totals?
  Generated SQL : SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary GROUP BY 1 ORDER BY 1 LIMIT 200
  Executed OK   : True
  Result Match  : True
  Latency       : 8105 ms

Q07 [NOVEL]: How many total pages did I read in the last 14 days?
  Generated SQL : SELECT SUM(pages_read) AS total_pages FROM v_daily_summary WHERE date >= CURRENT_DATE - 14 LIMIT 200
  Executed OK   : True
  Result Match  : True
  Latency       : 8380 ms

Q08 [FEW-SHOT OVERLAP]: What are my top 3 screen-time categories?
  Generated SQL : SELECT category, SUM(minutes) AS total FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 3
  Executed OK   : True
  Result Match  : True
  Latency       : 7209 ms

Q09 [NOVEL]: What is my average HRV on days with >=1 commit compared to days with 0 commits?
  Generated SQL : SELECT ROUND(CAST(AVG(hrv_ms) AS DECIMAL), 2) AS avg_hrv_commits, ROUND(CAST(AVG(hrv_ms) AS DECIMAL), 2) AS avg_hrv_no_commits FROM v_daily_summary, (SELECT ROUND(CAST(AVG(hrv_ms) AS DECIMAL), 2) AS avg_hrv_commits FROM v_daily_summary WHERE commits = 0) AS no_commits WHERE commits > 0 LIMIT 200
  Executed OK   : True
  Result Match  : False (actual=[[53.19, 53.19]] vs expected=[[53.19, 45.42]])
  Latency       : 9727 ms

Q10 [NOVEL]: What is my longest streak of consecutive commit days?
  Generated SQL : WITH commit_days AS (SELECT date, commits, LAG(commits) OVER (ORDER BY date) AS prev_commits FROM v_daily_summary) SELECT MAX(date - prev_commits) AS streak FROM commit_days WHERE commits > 0 AND prev_commits > 0 LIMIT 200
  Executed OK   : False ((psycopg.errors.UndefinedFunction) operator does not exist: date - bigint)
  Result Match  : False (actual=[] vs expected=[[16]])
  Latency       : 22573 ms

=== BENCHMARK TOTALS ===
Executed OK                  : 9/10
Exact/Tolerance Result Match : 6/10
  Few-shot overlap (Q1,4,6,8): 4/4
  Non-overlap (Q2,3,5,7,9,10): 2/6
Total Latency                : 88.47s (avg 8847 ms/question)
```

### 4. Live API Curl Check (`X-API-Key` Masked as `***`)
```powershell
curl.exe -s -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -H "X-API-Key: ***" -d "{\"question\":\"What was my average sleep on days I pushed code?\"}"
```
```json
{"question":"What was my average sleep on days I pushed code?","standalone_question":"What was my average sleep on days I pushed code?","sql":"SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200","explanation":"Calculates the average sleep hours on days when code was pushed.","columns":["avg_sleep"],"rows":[[7.44]],"row_count":1,"summary":"Your average sleep on days you pushed code was 7.44 hours.","model":"ollama/llama3.1:8b","latency_ms":9334}
```
- Unauthenticated `POST /v1/query`: `401 Unauthorized`
- `query_log` confirmed written (`id=1`, `endpoint=/v1/query`, `ok=t`, `latency_ms=9334`)
- Ruff lint check across all Step 0 & Phase 5 files: `All checks passed!`
- Secret scan `git grep -nE "gh[p]_|s[k]-|AI[z]a"`: Exit 1 (0 matches)

---

## 5. Problems and Fixes

- **Seed date-shift & contradicting copy**: Fixed with `SEED_END_DATE=2026-11-23`, `--reset` truncated tables, metric-driven sleep copy, no `"Day N"`, max 1 journal/reading note per date.
- **Query rewrite drift (`llama3.1:8b`)**: `test_live_ollama_query_rewrite` initially failed when `"How about sleep?"` rewrote to `"November 2026"` commits; setting `temperature=0.0` in `call_structured` and refining `rewrite.py`'s system prompt resolved it reliably.
- **SQLGlot `Anonymous` function names**: `pg_sleep(10)` parses as `exp.Anonymous(this='pg_sleep')` where `.sql_name()` returns `'ANONYMOUS'`. Extracted `.this` on `exp.Anonymous` nodes so all blocked/`pg_*` functions are reliably intercepted.
- **`query_log` rollback on HTTP errors**: FastAPI `Depends(get_rw_session)` rolls back uncommitted changes when raising `HTTPException`; persisting `query_log` inside `finally:` using its own short RW session ensures every success and error (`400`/`422`) is logged durably.

---

## 6. How to Verify Yourself

```powershell
# 1. Start DB container and reset seed deterministically
docker compose up -d db
python -m scripts.seed --reset

# 2. Run Phase 5 security, golden, and query tests
python -m pytest tests/security tests/golden tests/integration/test_query.py -q

# 3. Run full test suite (requires Ollama running llama3.1:8b)
python -m pytest -q

# 4. Run optional live Text-to-SQL benchmark
python -m scripts.bench_sql

# 5. Start API and verify /v1/query (replace *** with APP_API_KEY from .env)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
curl.exe -s -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -H "X-API-Key: ***" -d "{\"question\":\"What was my average sleep on days I pushed code?\"}"
```

---

## 7. Known Limitations

- **Few-shot vs Novel SQL Accuracy**: On `llama3.1:8b` (`num_ctx=4096`), `bench_sql.py` hits `4/4` on questions matching the embedded few-shot examples (`Q1, Q4, Q6, Q8`) versus `2/6` on novel questions (`Q3` missing `ORDER BY/LIMIT`, `Q9` cross-join bug instead of `FILTER`, `Q10` invalid `date - bigint` streak SQL, `Q2` off-by-1 because `CURRENT_DATE` is `2026-11-25` vs `SEED_END_DATE=2026-11-23`).
- **Pre-existing Ruff Warnings**: Phase 2/3 files not touched in Phase 5 retain a few minor ruff style hints (e.g. `typing.Pattern` import in `pii.py`), scheduled for Phase 9 hardening (`ruff check .` clean gate).
