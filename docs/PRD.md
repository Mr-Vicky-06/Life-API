# PRD — Life-API (Personal API for Your Life)

## 1. Problem
Personal data (sleep, workouts, commits, reading, screen time) is siloed in separate apps. The owner cannot ask cross-source questions ("How did my sleep affect my commits last month?").

## 2. Product
One owner-controlled API + dashboard that unifies the data, answers natural-language questions, and returns strictly structured JSON. Single-user, local-first, privacy-first.

## 3. Users
Single user (the owner). No signup, no multi-tenancy. Access protected by one API key (`APP_API_KEY`).

## 4. In Scope (MVP)
| ID | Feature |
|----|---------|
| F1 | Ingestion: GitHub (PAT), CSV/JSON import for health, reading, screen time, notes; deterministic seed generator |
| F2 | Storage: Postgres 16 + pgvector; migrations via Alembic |
| F3 | Cleaning: dedupe, strip HTML/Markdown noise, UTC normalization |
| F4 | Text-to-SQL over allowlisted read-only views |
| F5 | Hybrid search over notes (Postgres full-text + vector, fused with RRF) |
| F6 | Query rewriting for follow-ups ("how about last week?") |
| F7 | Model Gateway: LiteLLM, local (Ollama) default, cloud optional, retries, fallbacks, cost/latency log |
| F8 | PII masking + reverse map; input and output guardrails |
| F9 | Structured outputs: Pydantic-validated JSON with repair + retry |
| F10 | REST API (`/v1/*`) per `API_SPEC.md` |
| F11 | ReAct life-agent (tools: sql_query, search_notes, get_metrics) |
| F12 | Streamlit dashboard: metric charts, correlation chart, chat panel |

## 5. Out of Scope (do NOT build)
Mobile app, multi-user auth, OAuth flows for Fitbit/Oura/Apple Health (use CSV/JSON export instead), write-back to any external service, payments, deployment automation.

## 6. Non-Functional Requirements
- `/v1/query` p95 < 15 s on local Ollama; < 6 s on cloud model.
- Zero raw PII in any outbound cloud request (verified by test).
- LLM-generated SQL can never mutate data (verified by test).
- Fresh clone to running app in under 10 minutes using the Commands in `ANTIGRAVITY.md`.

## 7. Acceptance Criteria (project-level)
1. `python -m scripts.seed` creates 90 days of data in all tables.
2. `POST /v1/query {"question":"What was my average sleep on days I pushed code?"}` returns schema-valid JSON containing the executed SQL, rows, and a summary, with a number matching the hand-written golden SQL in tests.
3. `POST /v1/search` returns hybrid-ranked note chunks with scores.
4. A prompt containing an email and a GitHub token reaches the mocked cloud provider with placeholders only; the user-visible answer has them restored.
5. Malicious SQL (`DROP`, multi-statement, `pg_sleep`, non-allowlisted table) is rejected with HTTP 422.
6. Dashboard shows sleep vs commits correlation and a working chat box.
7. `pytest -q` passes with zero failures.

## 8. Success Metric
Owner can answer any of the 10 golden questions in `TESTING.md` correctly from the dashboard chat.
