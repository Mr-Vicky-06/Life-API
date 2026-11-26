# Phase 8: Dashboard & Screen-Time API Endpoint
Date: 2026-11-25 | Branch: phase-8-dashboard | Status: Complete

## 1. Objective

Implement **Step 0** (`GET /v1/screen-time`) and **Phase 8** (Streamlit + Plotly multi-tab dashboard in [dashboard/app.py](file:///d:/LIFE_API/dashboard/app.py)) communicating strictly with the FastAPI HTTP backend via [api_client.py](file:///d:/LIFE_API/dashboard/api_client.py), with zero `app.*` imports, zero direct DB access, zero `statsmodels`, and zero `unsafe_allow_html`.

---

## 2. Step 0: `GET /v1/screen-time` Addition

- Added `ScreenTimeCategory(category: str, minutes: int)` in [app/schemas/metrics.py](file:///d:/LIFE_API/app/schemas/metrics.py).
- Extracted shared `validate_date_range()` and added `query_screen_time()` in [app/metrics.py](file:///d:/LIFE_API/app/metrics.py), reading `v_screen_time` exclusively through the `life_ro` session (`SUM(minutes)` ordered by `minutes DESC, category ASC`, range validated `from <= to` and `<= 366` days).
- Registered `GET /v1/screen-time` (`Query(alias="from")`, `Query(alias="to")`) with `X-API-Key` auth and standard error envelope in [routes_metrics.py](file:///d:/LIFE_API/app/api/routes_metrics.py); updated [API_SPEC.md](file:///d:/LIFE_API/docs/API_SPEC.md).

**Live curl gate (`http://127.0.0.1:8000`):**
```text
HEALTH:
{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"none"}
SCREEN-TIME:
[{"category":"Productivity","minutes":1536},{"category":"Entertainment","minutes":551},{"category":"Social","minutes":410}]
```

---

## 3. What Was Built (`dashboard/`, `.streamlit/`, Scripts, Docs)

- [.streamlit/config.toml](file:///d:/LIFE_API/.streamlit/config.toml): `[server]` sets `address = "127.0.0.1"`, `port = 8501`, `headless = true`, `showEmailPrompt = false`; `[browser]` sets `gatherUsageStats = false`.
- [dashboard/config.py](file:///d:/LIFE_API/dashboard/config.py): `DashboardConfig` (`pydantic-settings`) loading `API_URL` (default `http://127.0.0.1:8000`) and `APP_API_KEY`.
- [dashboard/api_client.py](file:///d:/LIFE_API/dashboard/api_client.py): Stateless `httpx.Client` wrapper sending `X-API-Key` with `30.0 s` timeout for data endpoints (`/v1/metrics`, `/v1/screen-time`, `/v1/insights/daily`, `/v1/search`) and `120.0 s` timeout for `/v1/agent/chat`; maps unreachable errors (showing `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`), `401` (`API key rejected, check APP_API_KEY in .env`), `404`, `422`, `400`, `429`, `503`, and timeouts to sanitized messages scrubbing `APP_API_KEY` and tracebacks.
- [dashboard/charts.py](file:///d:/LIFE_API/dashboard/charts.py): Pure figure builders (`build_sleep_commits_figure` using `numpy.polyfit` OLS trendline and `numpy.corrcoef` Pearson `r`, `build_steps_figure`, `build_screen_time_figure`) and `compute_period_kpis`.
- [dashboard/app.py](file:///d:/LIFE_API/dashboard/app.py):
  - Sidebar date range picker bounded to available dates returned by a 366-day `/v1/metrics` lookup (defaults to the last 30 days of available data: `2026-10-25` to `2026-11-23`), with `st.info` fallback when empty.
  - `@st.cache_data(ttl=60, show_spinner=False)` wrappers that exclude `api_key` from cache parameters.
  - **Overview tab**: 4 `st.metric` KPIs with equal-length prior-period deltas + 3 Plotly charts + `"Correlation, not causation"` caption.
  - **Daily Insight tab**: Lazy generation only when `"Generate insight"` button is clicked (`never` auto-called on page load/rerun).
  - **Search Notes tab**: Query + `source_type` selector + optional date range filter rendering snippets safely via `st.text` inside `st.container(border=True)`.
  - **AI Chat tab**: UUID `session_id` validated against `[A-Za-z0-9_-]{1,64}`, `st.chat_input` + `st.chat_message`, plus per-reply expander with latency (`ms`), steps, and SQL code block.
- Updated [scripts/dev.ps1](file:///d:/LIFE_API/scripts/dev.ps1) (`-Dashboard` switch on `127.0.0.1:8501` using `python -m streamlit`), [README.md](file:///d:/LIFE_API/README.md) (`Run locally` + Build Status), and [DECISIONS.md](file:///d:/LIFE_API/docs/DECISIONS.md).

---

## 4. Streamlit Startup & Automated Gate Results

**Streamlit startup log (`task-3853.log`, `python -m streamlit run dashboard/app.py`):**
```text
2026-11-25 21:32:32.674 Uvicorn server started on 127.0.0.1:8501

  You can now view your Streamlit app in your browser.

  URL: http://127.0.0.1:8501
```
(Confirmed bound to `127.0.0.1:8501`, zero email prompt, zero usage-stats prompt.)

**Ruff check (Phase 8 touched/added files):**
```text
.\.venv\Scripts\python.exe -m ruff check dashboard/ app/metrics.py app/schemas/metrics.py app/api/routes_metrics.py tests/integration/test_metrics.py tests/unit/test_dashboard_charts.py tests/unit/test_dashboard_client.py tests/integration/test_dashboard_app.py
All checks passed!
```
*(Repo-wide `ruff check .` exited 1 with 20 pre-existing lint items in earlier Phase 3/4 files: `app/gateway/pii.py`, `app/rag/hybrid.py`, `tests/integration/test_search.py`, `tests/security/test_pii.py`, `tests/test_live_rewrite.py`, `tests/unit/test_cleaning.py`, `tests/unit/test_rewrite.py`, `tests/unit/test_rrf.py`, `tests/unit/test_structured.py` — left untouched.)*

**Phase 8 unit & `AppTest` integration suite:**
```text
tests/unit/test_dashboard_charts.py::test_compute_sleep_commits_fit_linear_relationship PASSED [  9%]
tests/unit/test_dashboard_charts.py::test_compute_sleep_commits_fit_handles_constant_and_missing_rows PASSED [ 18%]
tests/unit/test_dashboard_charts.py::test_compute_period_kpis_values_and_deltas PASSED [ 27%]
tests/unit/test_dashboard_charts.py::test_figure_builders_handle_normal_and_empty_inputs PASSED [ 36%]
tests/unit/test_dashboard_client.py::test_client_sends_api_key_header_and_parses_endpoints PASSED [ 45%]
tests/unit/test_dashboard_client.py::test_client_maps_401_422_503_and_scrubs_api_key PASSED [ 54%]
tests/unit/test_dashboard_client.py::test_client_maps_connect_error_and_timeout PASSED [ 63%]
tests/integration/test_dashboard_app.py::test_dashboard_static_isolation_and_cache_safety PASSED [ 72%]
tests/integration/test_dashboard_app.py::test_app_renders_kpis_charts_and_lazy_insight_generation PASSED [ 81%]
tests/integration/test_dashboard_app.py::test_app_shows_friendly_unreachable_and_401_banners PASSED [ 90%]
tests/integration/test_dashboard_app.py::test_app_chat_and_search_workflows PASSED [100%]

11 passed in 26.94s
```

**Full repository test suite (`python -m pytest -q` after final code edit):**
```text
196 passed, 2 warnings in 293.02s (0:04:53)
```

---

## 5. Visual Verification & `TESTING.md` §6 Checklist

`VISUAL CHECK`: Re-verified live in headless Chromium via Playwright (`http://127.0.0.1:8501`) after populating PostgreSQL with real researched open datasets ([real-data-provenance.md](file:///d:/LIFE_API/reports/real-data-provenance.md)); `browser_console_messages(level="error")` returned `0` errors and `0` warnings across all tested panels.

Screenshots captured in [reports/phase-8/](file:///d:/LIFE_API/reports/phase-8) (showing real Eindhoven/Fitbit, `Mr-Vicky-06`, Goodreads, ScreenTime-App-Details, and VAD journal data):
- [overview.png](file:///d:/LIFE_API/reports/phase-8/overview.png): Default 30d window (`2026-10-28` to `2026-11-26`), KPIs (`Avg Sleep 7.29 h`, `Total Commits 83`, `Avg Steps 4,998`, `Total Reading 6,684 min`), Sleep vs Commits OLS scatter (`r = 0.275, n = 30`, `"Correlation, not causation"`), Steps line chart.
- [screentime.png](file:///d:/LIFE_API/reports/phase-8/screentime.png): Screen time by category bar chart (`Social`, `Productivity`, `Entertainment` descending).
- [insight.png](file:///d:/LIFE_API/reports/phase-8/insight.png): `"Generate insight"` click for `2026-11-26` rendered summary (`8.27 hours`, `1` commit, `470 minutes` reading, `54` steps, `560 minutes` screen time), comparison insight, and 5 metric cards.
- [search.png](file:///d:/LIFE_API/reports/phase-8/search.png): Search `"slept tired"` rendered real dated diary hits (`2026-11-23 | journal | score=0.0164`, `2026-10-05 | journal | score=0.0161`).
- [chat.png](file:///d:/LIFE_API/reports/phase-8/chat.png): Chat `"What was my average sleep on days I pushed code?"` rendered `7.41 hours` and expanded `Steps (2) | Latency: 12633 ms` with the generated SQL (`SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200`).

### `docs/TESTING.md` §6 Checklist Status
- [x] KPIs populated after ingest (verified live in `overview.png` + Playwright snapshot)
- [x] Scatter chart shows sleep vs commits with trendline (verified live in `overview.png`, `r = 0.275, n = 30`)
- [x] Date range filter changes charts (verified live in Playwright by selecting `2026-09-01..2026-09-30` in sidebar calendar)
- [x] Chat: `"What was my average sleep on days I pushed code?"` returns an answer with the SQL expander visible (verified live in `chat.png`)
- [x] Search box returns snippets with dates (verified live in `search.png`)
- [ ] Wrong API key shows a clear error, not a stack trace (*Verified by automated `respx` + `AppTest` tests in [test_dashboard_client.py](file:///d:/LIFE_API/tests/unit/test_dashboard_client.py) and [test_dashboard_app.py](file:///d:/LIFE_API/tests/integration/test_dashboard_app.py); not manually triggered with a bad `.env` in Playwright*)

---

## 6. Known Limitations & Cleanup Verification

- **Cold Ollama insight load vs 30 s data timeout:** On the first click of `"Generate insight"` (`2026-11-23`), Ollama took `31293.8 ms` to load `qwen2.5-coder:7b`, hitting the `30.0 s` `DATA_TIMEOUT_S` client timeout and displaying `"Request timed out while waiting for the API. Please try again."` cleanly; retrying once warm succeeded. Kept `DATA_TIMEOUT_S = 30.0` (`AGENT_TIMEOUT_S = 120.0`) as specified.
- **Process cleanup & secret scan:** Both `uvicorn` and `streamlit` processes were stopped (`OPEN_LISTEN_COUNT=0` on ports `8000` and `8501`). Verified zero secrets via `git grep -nE "gh[p]_|s[k]-|AI[z]a"`.
