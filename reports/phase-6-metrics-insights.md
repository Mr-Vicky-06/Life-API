# Phase 6: Metrics + Insights API
Date: 2026-11-25 | Branch: phase-6-metrics | Status: Complete

## 1. Objective

Implement read-only time-series metrics (`GET /v1/metrics`) and DB-grounded daily LLM insights (`GET /v1/insights/daily`) backed strictly by `v_daily_summary` through the `life_ro` role, validate all parameters and narratives safely, verify `Q06` prompt isolation in Step 0, and pass all unit, integration, security, live Ollama, and curl gates.

---

## 2. Step 0: Q06 Prompt Contamination Check (Two Attempts)

### Initial Failure & Prompt Context
Golden `Q06` (`"What are my weekly commit totals?"`) previously failed with a spurious `- 7` filter copied from the relative-window example:
```sql
SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits
FROM v_daily_summary
WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE)
GROUP BY 1 ORDER BY 1 LIMIT 200
```
Original few-shot prompt block around the examples in `app/sql_agent/schema_prompt.py`:
```text
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
```

### Attempts & Outcome
- **Attempt 1:** Separated every example into its own `<example id="..." shape="..."> ... </example>` block with explicit shapes and re-ran `Q06` only:
  - Generated SQL: `SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE) ORDER BY week LIMIT 200` (repaired to `GROUP BY week`, `Executed OK: True`, `Result Match: False`, `36040 ms`).
- **Attempt 2:** Separated every example into distinct `### Example N` blocks delimited by `---`, gave every example a distinct query shape (scalar avg, correlation, unbounded `date_trunc` rollup, `v_screen_time` Top-N, argmax, `FILTER`, `WITH` streak, and moved the relative window to Example 8 on `v_reading` with `- 5` so `- 7` no longer appeared in any example), then re-ran `Q06` only:
  ```text
  Q06 [GOLDEN OVERLAP]: What are my weekly commit totals?
    Generated SQL : SELECT CAST(DATE_TRUNC('WEEK', date) AS DATE) AS week, SUM(commits) AS commits FROM v_daily_summary WHERE date > CAST('2026-11-23' AS DATE) - 7 AND date <= CAST('2026-11-23' AS DATE) GROUP BY 1 ORDER BY 1 LIMIT 200
    Executed OK   : True
    Result Match  : False (actual=[['2026-11-16', 26.0], ['2026-11-23', 1.0]] vs expected=[['2026-08-24', 17], ['2026-08-31', 42], ['2026-09-07', 21]])
    Latency       : 13866 ms (gen=13743, val=39, exec=83)
  ```
- Kept the clean delimited block structure without special-casing `Q06`, and recorded it under Known Limitations below.

---

## 3. What Was Built

- **Schemas ([metrics.py](file:///d:/LIFE_API/app/schemas/metrics.py), [insights.py](file:///d:/LIFE_API/app/schemas/insights.py)):** Added `MetricsResponse` (`from_date`, `to_date`, `rows`) and `DailyInsight` (`timestamp`, `summary <= 300`, `metrics`, `insights <= 400`) matching [API_SPEC.md](file:///d:/LIFE_API/docs/API_SPEC.md).
- **Exceptions & Docs ([exceptions.py](file:///d:/LIFE_API/app/gateway/exceptions.py), [API_SPEC.md](file:///d:/LIFE_API/docs/API_SPEC.md)):** Added `ValidationError` (`422 validation_error`) and `NotFoundError` (`404 not_found`); documented `not_found`(404) in [API_SPEC.md](file:///d:/LIFE_API/docs/API_SPEC.md).
- **Shared JSON Serialization ([executor.py](file:///d:/LIFE_API/app/sql_agent/executor.py)):** Exposed `to_json_safe` cleanly for reuse across `/v1/metrics` and `/v1/insights/daily`.
- **Metrics Route ([routes_metrics.py](file:///d:/LIFE_API/app/api/routes_metrics.py)):**
  - `GET /v1/metrics` with `Query(alias="from")`, `Query(alias="to")`, and optional `metrics`.
  - Allowlisted 11 metrics mapping strictly to `v_daily_summary` columns (`sleep_hours`, `sleep_score`, `deep_sleep_min`, `hrv_ms`, `resting_hr`, `steps`, `commits`, `lines_added`, `pages_read`, `reading_minutes`, `screen_minutes`); defaults to all 11 when omitted.
  - Enforces `from <= to`, range `<= 366` days, and known metric names (`422 validation_error` listing allowed names); reads via `get_ro_session` (`life_ro`, bound date params, `ORDER BY date`); skips missing days.
- **Daily Insights Route ([routes_insights.py](file:///d:/LIFE_API/app/api/routes_insights.py)):**
  - `GET /v1/insights/daily` with optional `date` defaulting to latest `date <= REFERENCE_DATE` in `v_daily_summary`; missing dates return `404 not_found`.
  - Reads DB-only day numbers (`sleep_hours`, `github_commits`, `reading_minutes`, `steps`, `screen_minutes`) and 7-day averages (`date > target - 7 AND date <= target`) via `get_ro_session`.
  - Wraps numeric JSON only in `<data>` (never includes note text), calls `call_structured(DailyInsightText, ...)`, runs `check_output` and `verify_summary_numbers`.
  - Caches verified LLM prose in memory keyed by `(date, sha256(date, metrics, averages))`; never caches fallbacks caused by LLM failure or verification failure; always returns `200` with deterministic DB template on LLM errors or unverified numbers.
- **App Registration & Tests ([main.py](file:///d:/LIFE_API/app/main.py), [test_metrics.py](file:///d:/LIFE_API/tests/integration/test_metrics.py), [test_insights.py](file:///d:/LIFE_API/tests/integration/test_insights.py)):** Registered both routers with `X-API-Key` auth and added full integration, SQLi, cache/invalidation, prompt note-exclusion, fallback, and live Ollama tests.

---

## 4. Known Limitations

- **`v_daily_summary` Left-Join Base:** `v_daily_summary` starts from `health_daily`, so days with commits (or reading/screen entries) but no `health_daily` row are not visible to `/v1/metrics`, `/v1/insights/daily`, or Text-to-SQL. (The view was intentionally left unchanged in Phase 6.)
- **Golden Q06 (`weekly commit totals`) with `qwen2.5-coder:7b`:** After two attempts delimiting every prompt example into separate blocks with distinct query shapes and removing `- 7` from all prompt examples, `qwen2.5-coder:7b` still associates the word `"weekly"` with a `- 7` date filter.
- **Runtime Python Version:** The workspace virtualenv runs Python `3.12.10` while [ARCHITECTURE.md](file:///d:/LIFE_API/docs/ARCHITECTURE.md) pins `3.11` (all dependencies and tests run cleanly).

---

## 5. Gate Outputs

### 1. Phase 6 Integration Suite (`test_metrics.py` & `test_insights.py`)
```powershell
python -m pytest tests/integration/test_metrics.py tests/integration/test_insights.py -q
```
```text
...........                                                              [100%]
11 passed in 77.60s (0:01:17)
```

### 2. Live Ollama Tests (`@pytest.mark.live`)
```powershell
python -m pytest tests/integration/test_insights.py -m live -s -W ignore
```
```text
LIVE DAILY INSIGHT (14286 ms): {"timestamp":"2026-11-02","summary":"Today, you slept 8.01 hours, made 6 GitHub commits, took no reading time, walked 11,807 steps, and spent 362 minutes on screens.","metrics":{"sleep_hours":8.01,"github_commits":6,"reading_minutes":0,"steps":11807,"screen_minutes":362},"insights":"You slept well tonight and made more GitHub commits than average for the week. However, you spent more time on screens than usual. Consider setting a goal to reduce screen time to match your recent average."}
.
1 passed, 6 deselected in 94.12s (0:01:34)
```
```powershell
python -m pytest -m live -q -W ignore
```
```text
....                                                                     [100%]
4 passed, 160 deselected in 134.74s (0:02:14)
```

### 3. Full Repository Test Suite
```powershell
python -m pytest -q
```
```text
........................................................................ [ 43%]
........................................................................ [ 87%]
....................                                                     [100%]
============================== warnings summary ===============================
tests/integration/test_search.py::test_api_search_validation_errors
  D:\LIFE_API\.venv\Lib\site-packages\starlette\_exception_handler.py:59: StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
    response = await handler(conn, exc)  # type: ignore[arg-type]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
164 passed, 1 warning in 293.01s (0:04:53)
```

### 4. Live API Curl Checks (`X-API-Key` Masked as `***`)
```powershell
curl.exe -s "http://127.0.0.1:8000/v1/metrics?from=2026-11-01&to=2026-11-07&metrics=sleep_hours,commits" -H "X-API-Key: ***"
```
```json
{"from_date":"2026-11-01","to_date":"2026-11-07","rows":[{"date":"2026-11-01","sleep_hours":8.01,"commits":8},{"date":"2026-11-02","sleep_hours":8.01,"commits":6},{"date":"2026-11-03","sleep_hours":7.24,"commits":1},{"date":"2026-11-04","sleep_hours":6.13,"commits":0},{"date":"2026-11-05","sleep_hours":6.59,"commits":7},{"date":"2026-11-06","sleep_hours":7.96,"commits":4},{"date":"2026-11-07","sleep_hours":7.56,"commits":8}]}
```

```powershell
curl.exe -s "http://127.0.0.1:8000/v1/insights/daily?date=2026-11-02" -H "X-API-Key: ***"
```
```json
{"timestamp":"2026-11-02","summary":"Today, you slept 8.01 hours, made 6 GitHub commits, took no reading time, walked 11,807 steps, and spent 362 minutes on screens.","metrics":{"sleep_hours":8.01,"github_commits":6,"reading_minutes":0,"steps":11807,"screen_minutes":362},"insights":"You slept well tonight and made more GitHub commits than average for the week. However, you spent more time on screens than usual. Consider setting a goal to reduce screen time to match your recent average."}
```
`Port 8000 listeners after stop: 0`

### 5. Lint & Secret Scan
- `python -m ruff check` across all Phase 6 created/modified files: `All checks passed!`
- `git grep -nE "gh[p]_|s[k]-|AI[z]a"`: Exit 1 (`0` matches; clean).
