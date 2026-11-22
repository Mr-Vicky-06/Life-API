# ANTIGRAVITY.md — Master Instructions for the Build Agent

> Read this file FIRST, every session. It is the contract. If another doc conflicts with this file, this file wins.

## 1. Mission
Build **Life-API**: a personal, privacy-first API + dashboard that unifies the owner's data streams (GitHub, health/sleep, reading, screen time) into Postgres + pgvector, answers natural-language questions via **Text-to-SQL** and **Hybrid RAG**, routes LLM calls through a **Model Gateway** with **PII masking**, and returns **schema-enforced JSON**. A **Streamlit** dashboard and a **ReAct agent** sit on top.

## 2. Read Order (mandatory)
1. `docs/PRD.md` — what and why, scope, acceptance criteria
2. `docs/ARCHITECTURE.md` — layers, pinned tech stack, repo layout, env vars
3. `docs/DATA_AND_RAG.md` — DB schema, ingestion, chunking, hybrid search, text-to-SQL
4. `docs/API_SPEC.md` — endpoints + Pydantic/JSON schemas
5. `docs/AGENT_WORKFLOW.md` — build phases, gates, ReAct state machine
6. `docs/SECURITY.md` — PII, guardrails, SQL safety
7. `docs/TESTING.md` — tests, verification commands, definition of done

## 3. Golden Rules
1. **Never ask the user a question.** Every decision is already in the docs. If something is truly unspecified, choose the simplest option, and append one line to `docs/DECISIONS.md` (`date | decision | reason`). Then continue.
2. **Build strictly phase by phase** (`AGENT_WORKFLOW.md`). Do not start Phase N+1 until Phase N's gate command passes. Paste the gate output in your summary.
3. **Use ONLY the pinned stack** in `ARCHITECTURE.md`. Do not add libraries, frameworks, or services not listed.
4. **Everything configurable lives in `.env`** (see `.env.example`). Never hardcode model names, URLs, keys, or paths.
5. **No secrets in code, logs, tests, or commits.** Never print env values.
6. **All LLM calls go through `app/gateway/llm.py`.** No direct SDK calls anywhere else.
7. **All LLM-generated SQL goes through `app/sql_agent/validator.py` and runs as the read-only DB role.** No exceptions.
8. **All timestamps are stored in UTC**, displayed in `APP_TIMEZONE` (default `Asia/Kolkata`).
9. **Type everything** (Python 3.11 type hints, Pydantic v2 models). Run `ruff` and `mypy`-free basic checks only as defined in TESTING.md.
10. **Small, working increments.** After each phase: app starts, tests pass, `README.md` updated.
11. **No placeholder code.** No `pass`, `TODO`, or fake returns in finished phases.
12. **Deterministic seed data** (`random.seed(42)`) so tests are reproducible.

## 4. Commands (the only ones you need)
```
docker compose up -d db            # Postgres 16 + pgvector
alembic upgrade head               # migrations
python -m scripts.seed             # deterministic demo data (90 days)
uvicorn app.main:app --reload      # API on :8000
streamlit run dashboard/app.py     # UI on :8501
pytest -q                          # all tests
```

## 5. Do NOT
- Do not use CLIP for text (use the sentence-transformers model in ARCHITECTURE.md).
- Do not call it "BM25" in code — Postgres full-text (`tsvector`/`ts_rank_cd`) is the term-based leg.
- Do not let the LLM write to the database, ever.
- Do not send raw PII to a cloud model. Mask first, unmask locally.
- Do not use localStorage-style hacks, global mutable state, or background threads without need.
- Do not refactor finished phases unless a test fails.

## 6. Final Response Format (after each phase)
```
Phase N complete
Files created/changed: ...
Gate command: <cmd>
Gate output: <pasted>
Decisions logged: <count>
Next: Phase N+1
```
