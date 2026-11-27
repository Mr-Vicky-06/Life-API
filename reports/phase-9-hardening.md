# Phase 9: Hardening, Data Honesty, Security & Acceptance Verification
Date: 2026-11-27 | Branch: `phase-9-hardening` | Status: Complete (`phase-9-complete`, `v0.1.0`)

---

## 1. Step 0 — Phase 8 Close-Out Verification

- `phase-8-complete` confirmed tagged on `main` (`08c17b649703e593afd3af714680bc546aee67b0`, ancestor check exited `0`).
- Confirmed delivered and passing on `main`:
  - `GET /v1/screen-time` (`app/api/routes_metrics.py`, `app/metrics.py`, `docs/API_SPEC.md`, `tests/integration/test_metrics.py`) returning `[{"category":"Productivity","minutes":1536},{"category":"Entertainment","minutes":551},{"category":"Social","minutes":410}]` on seeded `2026-11-01..2026-11-07`.
  - Static dashboard isolation test (`test_dashboard_static_isolation_and_cache_safety` asserting zero `app.*` imports or `unsafe_allow_html`).
  - `.streamlit/config.toml` configured cleanly (`address = "127.0.0.1"`, `port = 8501`, `headless = true`, `showEmailPrompt = false`, `gatherUsageStats = false`).
  - `pytest tests/unit/test_dashboard_charts.py tests/unit/test_dashboard_client.py tests/integration/test_dashboard_app.py -q`: `11 passed in 15.43s`.

---

## 2. Step 1 — Data Honesty Correction

1. **Default synthetic seed restored:** Ran `python -m alembic upgrade head` (`0001_init -> 0002_nullable_reading_minutes`) and `python -m scripts.seed --reset`:
   `Seed completed: health=90ins/0upd, commits=398ins/0upd, reading=68ins/0upd, screen=270ins/0upd, notes=72ins/0skip`
   Idempotent re-run:
   `Seed completed: health=0ins/90upd, commits=0ins/398upd, reading=0ins/68upd, screen=0ins/270upd, notes=0ins/72skip`
2. **Opt-in composite loader & constructed linkages removed:**
   - [scripts/ingest_real_data.py](file:///d:/LIFE_API/scripts/ingest_real_data.py) refuses to run without `--composite-demo` and prints an explicit composite-data warning (`cross-source correlations are not meaningful`) plus advises `DATA_LABEL="Composite public datasets + my GitHub commits (not personal health data)"`.
   - [app/ingestion/real_data.py](file:///d:/LIFE_API/app/ingestion/real_data.py): removed `_systematic_sleep_score`, `_systematic_hrv`, commit-weighted `Productivity`/`Entertainment` splits, valence-based sleep matching (`V`), and `[Sleep: ..., Steps: ...]` note prefixes. Preserves `NULL` (`None`) for unmeasured `hrv_ms`, missing `sleep_score`, missing `resting_hr`, Fitbit `deep_sleep_min`, and Goodreads `reading_log.minutes` (supported by nullable [app/models/reading.py](file:///d:/LIFE_API/app/models/reading.py) + migration [0002_nullable_reading_minutes.py](file:///d:/LIFE_API/migrations/versions/0002_nullable_reading_minutes.py) + `COALESCE` in `v_daily_summary`).
3. **`DATA_LABEL` persistent UI badge & chart captions:** Added `DATA_LABEL` (`"Synthetic demo data"` default) in [app/config.py](file:///d:/LIFE_API/app/config.py), [dashboard/config.py](file:///d:/LIFE_API/dashboard/config.py), and [.env.example](file:///d:/LIFE_API/.env.example); rendered persistently in sidebar and below every Plotly chart (`"Data: Synthetic demo data"`) in [dashboard/app.py](file:///d:/LIFE_API/dashboard/app.py).
4. **License audit & CC-BY 4.0 attribution:** Updated [real-data-provenance.md](file:///d:/LIFE_API/reports/real-data-provenance.md) with verbatim findings (`no license found` for `health-hacks/datasets` and `JB3NNETT/Goodreads-TBR`, `MIT License` for `emadnahed/ScreenTimeAnalyzer`, `CC-BY-NC-4.0` for `mmarkusmalone/journal-entries-emotion-detection-vad`, `CC-BY 4.0` for Zenodo `15171250`), added full CC-BY 4.0 attribution (`Gogate, Eindhoven Univ. of Technology`), removed stale `reports/real-sources-summary.json` from Git (`git rm`), verified `0` raw third-party datasets tracked (`git ls-files`), and ensured `.cache/` and `data/raw/` remain gitignored.
5. **Regenerated labeled screenshots:** Re-captured all 5 views (`overview.png`, `screentime.png`, `insight.png`, `search.png`, `chat.png`) in [reports/phase-8/](file:///d:/LIFE_API/reports/phase-8) on labeled synthetic data (`0` browser console errors, updated [phase-8-dashboard.md](file:///d:/LIFE_API/reports/phase-8-dashboard.md)).
6. **`"Using your own data"` documentation:** Added CSV schemas, `POST /v1/ingest/*` usage, and `GITHUB_TOKEN`/`GITHUB_USERNAME` sync instructions to [README.md](file:///d:/LIFE_API/README.md).

---

## 3. Step 2A — Security Conformance Matrix (`docs/SECURITY.md` §2–7)

| Section | Requirement | Status | Implementation Evidence | Test Evidence |
|---|---|---|---|---|
| §2 PII Masking | `mask`/`unmask`, regexes (`EMAIL`, `PHONE`, `GH_TOKEN`, `API_KEY`, `GEO`, `HEALTH_ID`), per-request stable placeholders, memory-only mapping, non-`ollama/*` outbound + always on logs, local router note | Implemented & Tested | [app/gateway/pii.py](file:///d:/LIFE_API/app/gateway/pii.py), [app/gateway/llm.py](file:///d:/LIFE_API/app/gateway/llm.py) | [tests/security/test_pii.py](file:///d:/LIFE_API/tests/security/test_pii.py) (`6 passed`) |
| §3 Guardrails | Empty/max-length rejection; injection phrase block -> HTTP 400 `guardrail_blocked`; retrieved note `<data>` wrapping; secret + prompt-leak stripping in outputs | Implemented & Tested | [app/gateway/guardrails.py](file:///d:/LIFE_API/app/gateway/guardrails.py), [app/agent/react.py](file:///d:/LIFE_API/app/agent/react.py) | [tests/security/test_guardrails.py](file:///d:/LIFE_API/tests/security/test_guardrails.py), [tests/security/test_agent_injection.py](file:///d:/LIFE_API/tests/security/test_agent_injection.py) |
| §4 SQL Validator & Defense in Depth | 1 statement, `exp.Select` root, allowlist 4 views, blocked `pg_*`/unsafe functions, comment `;`/`INTO`/`FOR UPDATE`/`LOCK` rejected, `LIMIT 200` added/clamped + Postgres normalized + `life_ro` role + `5000ms` timeout in RO tx | Implemented & Tested | [app/sql_agent/validator.py](file:///d:/LIFE_API/app/sql_agent/validator.py), [app/sql_agent/executor.py](file:///d:/LIFE_API/app/sql_agent/executor.py), [0001_init.py](file:///d:/LIFE_API/migrations/versions/0001_init.py) | [tests/security/test_sql_validator.py](file:///d:/LIFE_API/tests/security/test_sql_validator.py), [tests/security/test_ro_executor.py](file:///d:/LIFE_API/tests/security/test_ro_executor.py) |
| §5 Secrets & Logging | `.env` gitignored, `.env.example` secret-free, `RedactingFilter` strips PII + `APP_API_KEY` + `GITHUB_TOKEN`, `query_log.question_masked` stores masked question | Implemented & Tested | [.gitignore](file:///d:/LIFE_API/.gitignore), [.env.example](file:///d:/LIFE_API/.env.example), [logging_filter.py](file:///d:/LIFE_API/app/gateway/logging_filter.py), [routes_query.py](file:///d:/LIFE_API/app/api/routes_query.py) | [tests/unit/test_log_redaction.py](file:///d:/LIFE_API/tests/unit/test_log_redaction.py), [tests/integration/test_query.py](file:///d:/LIFE_API/tests/integration/test_query.py) |
| §6 API Access | Constant-time `hmac.compare_digest`, non-dev default key rejection, CORS `http://localhost:8501` only, 60 req/min per-key in-memory middleware (429 envelope) | Implemented & Tested | [app/deps.py](file:///d:/LIFE_API/app/deps.py), [app/config.py](file:///d:/LIFE_API/app/config.py), [app/main.py](file:///d:/LIFE_API/app/main.py) | [tests/security/test_api_security.py](file:///d:/LIFE_API/tests/security/test_api_security.py), [tests/security/test_startup_security.py](file:///d:/LIFE_API/tests/security/test_startup_security.py) |
| §7 Privacy Mode | `CLOUD_LLM_ENABLED=false` default refuses cloud models; enabling `cloud_llm_enabled=true` logs explicit startup warning about masked outbound prompts | Gap fixed & Tested | [app/gateway/llm.py](file:///d:/LIFE_API/app/gateway/llm.py), `validate_startup_security` in [app/config.py](file:///d:/LIFE_API/app/config.py) | `test_cloud_llm_enabled_logs_startup_warning` in [test_startup_security.py](file:///d:/LIFE_API/tests/security/test_startup_security.py) |

---

## 4. Step 2B — PRD Acceptance Criteria Matrix (`docs/PRD.md` §7, Synthetic Data)

| # | Acceptance Criterion | Command / Verification Run | Observed Result |
|---:|---|---|---|
| 1 | `python -m scripts.seed` creates 90 days across all tables (idempotent on re-run) | `python -m scripts.seed --reset` then `python -m scripts.seed` | `health=90ins/0upd, commits=398ins/0upd, reading=68ins/0upd, screen=270ins/0upd, notes=72ins/0skip`; 2nd run: `0ins` across all tables |
| 2 | `POST /v1/query` (`"What was my average sleep on days I pushed code?"`) returns schema-valid JSON matching golden expected | Live API `POST http://127.0.0.1:8000/v1/query` + `test_golden_sql.py` | HTTP `200`: `sql="SELECT ROUND(CAST(AVG(sleep_hours) AS DECIMAL), 2) AS avg_sleep FROM v_daily_summary WHERE commits > 0 LIMIT 200"`, `rows=[[7.44]]`, `summary="Result: avg_sleep: 7.44."` |
| 3 | `POST /v1/search` returns hybrid-ranked note chunks with scores | Live API `POST http://127.0.0.1:8000/v1/search` (`{"query":"slept badly","top_k":3}`) | HTTP `200`: `3` hits led by `note_id=23`, `2026-09-20`, `source_type="journal"`, `score=0.032787` |
| 4 | Email + GitHub token masked to placeholders in mocked cloud outbound payload and restored locally | `python -m pytest tests/security/test_pii.py -v` | `6 passed in 13.73s` (`test_cloud_llm_outbound_pii_masked_and_inbound_unmasked PASSED`) |
| 5 | Malicious SQL (`DROP`, multi-statement, `pg_sleep`, non-allowlisted table) rejected with HTTP 422 (`sql_rejected`) | `tests/security/test_sql_validator.py` + `tests/integration/test_query.py` | All disallowed SQL patterns raise `SQLRejected(status_code=422, code="sql_rejected")`; live `/v1/query` injection string returns HTTP `400` (`guardrail_blocked`) |
| 6 | Dashboard shows sleep vs commits correlation and working AI chat box | Playwright verification on `http://127.0.0.1:8501` | Scatter renders `r = 0.733, n = 30` with `Data: Synthetic demo data` caption; AI Chat returned `7.44 hours` (`Steps (2) \| Latency: 13588 ms`) with `0` console errors |
| 7 | Non-live & live suites pass with 0 failures | `python -m pytest -m "not live" -q` and `python -m pytest -m live -q -W ignore` | `202 passed, 1 skipped, 5 deselected`; `5 passed, 203 deselected` |

---

## 5. Step 2C–2G — Hardening Fixes, Lint, Dependencies & Fresh Clone

- **Q06 (`app/sql_agent/generator.py`):** Added generic AST guard `has_spurious_date_window()` + `has_time_window_expression()` checking whether a `WHERE` clause emits a date range filter when the question asks across all rows without a timeframe; regenerates once if triggered. Tested in [test_sql_generator.py](file:///d:/LIFE_API/tests/unit/test_sql_generator.py).
  - Live `python -m scripts.bench_sql` (`ollama/qwen2.5-coder:7b`): **`22/22`** (`10/10` golden including `Q06`, `12/12` held-out; `has_spurious_date_window` caught and repaired spurious `- 7` filters live on `Q06` & `Q08`; mean `5152 ms`, max `15212 ms`).
- **B07 (`app/agent/react.py`):** Reproduced raw `last_obs[:400]` JSON slice bug when `search_notes` JSON list exceeded `MAX_OBSERVATION_CHARS=1500`; added `_salvage_note_hits()` (`json.JSONDecoder().raw_decode` + partial-hit regex) in `_parse_observation_or_salvage()` for both `_plain_values_fallback()` and `_build_verification_rows()`. Verified by `test_plain_values_fallback_salvages_truncated_search_notes_json`.
- **B13 (`app/agent/react.py`):** Added compound-question multi-tool rule (Rule 5 + routing example) in `_build_system_prompt()`, tested in `test_system_prompt_includes_compound_multi_tool_rule`.
  - Live `python -m scripts.bench_agent` (`ollama/qwen2.5-coder:7b`): **`15/15` Tool Match (100%)**, **`15/15` Answer Accuracy (100%)** (`B07` and `B13` both `True`; mean `13809 ms`, max `22370 ms`, total `207.14s`).
- **`GET /health` router (`app/api/routes_health.py`):** Reports configured router (`settings.router_model.strip().lower() or "none"`) while keeping distinct `"connection refused"`, `"timed out"`, and `"model not found"` diagnostics in `llm_detail`. Live `/health`: `{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"general"}`.
- **Optional GitHub live test (`tests/test_live_github.py`):** Registered `live_github` marker in `pyproject.toml`, skipped cleanly when `GITHUB_TOKEN` is unset (without ever logging secrets).
- **Repo-wide lint & pinned `requirements.lock`:** Fixed all lint issues repo-wide (`python -m ruff check .` -> `All checks passed!`), aligned Python `3.11+` (`tested on Python 3.12.10`) notes, generated portable 117-package [requirements.lock](file:///d:/LIFE_API/requirements.lock).
- **Isolated fresh-clone verification (`Step 2F`):** Cloned `phase-9-hardening` from `origin` into temp `%TEMP%\lifeapi_fresh_test` with `COMPOSE_PROJECT_NAME=lifeapi_fresh` and `DB_PORT=5433` (never touching dev DB `5432` or dev dir):
  - Created fresh `.venv` + installed `requirements.lock` + configured `.env` from `.env.example` with generated `APP_API_KEY` + `DB_PORT=5433`.
  - `docker compose -p lifeapi_fresh up -d db` -> `alembic upgrade head` (`0001_init -> 0002_nullable_reading_minutes`) -> `python -m scripts.seed` -> `pytest -m "not live" -q` (`202 passed, 1 skipped, 5 deselected in 143.73s`).
  - Started API + dashboard (`FRESH_HEALTH={"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"general"}`, `FRESH_DASHBOARD_HTTP=200`), stopped listeners (`FRESH_CLEANUP_OPEN_LISTEN_COUNT=0`), tore down `lifeapi_fresh` containers/volumes (`down -v`), and removed temp directory (`TEMP_DIR_EXISTS=False`).

---

## 6. Final Gate Outputs

```text
python -m ruff check .
All checks passed!

python -m pytest -m "not live" -q
202 passed, 1 skipped, 5 deselected, 2 warnings

python -m pytest -m live -q -W ignore
5 passed, 203 deselected

git grep -nE "gh[p]_|s[k]-|AI[z]a"
GIT_GREP_EXIT=1

OPEN_LISTEN_COUNT=0 (ports 8000, 8501)
```
