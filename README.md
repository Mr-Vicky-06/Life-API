# Life-API — Personal API for Your Life

A privacy-first, local-first API + dashboard that unifies GitHub commits,
health/sleep metrics, reading logs, screen time, and journal notes into
PostgreSQL 16 + pgvector, with natural-language query, hybrid RAG, and a
Streamlit dashboard.

## Architecture

```
Data Streams (GitHub | CSV health/reading/screen-time | notes)
        │
L1  Ingestion (fetch → clean → dedupe → UTC → load)
        │   Postgres 16 + pgvector
L2  Context: Text-to-SQL | Hybrid Search (FTS + vector, RRF) | Query Rewrite
        │
L3  Model Gateway: LiteLLM | PII mask/unmask | guardrails | retries
        │
L4  FastAPI /v1/*  ──  Streamlit :8501  ──  ReAct agent
```

## Quickstart

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd life-api

# 2. Copy and fill the env file
cp .env.example .env   # edit APP_API_KEY; optionally set GITHUB_TOKEN

# 3. Start Postgres
docker compose up -d db

# 4. Create a venv and install dependencies
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e ".[dev]"

# 5. Run migrations
alembic upgrade head

# 6. Seed deterministic demo data (90 days)
python -m scripts.seed

# 7. Start the API
uvicorn app.main:app --reload   # → http://localhost:8000

# 8. Start the dashboard
streamlit run dashboard/app.py  # → http://localhost:8501
```

## Run locally

Using the automated development runner (Windows PowerShell):
```powershell
.\scripts\dev.ps1
```

Or manually:
```powershell
# 1. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Start the database container and wait for health
docker compose up -d db

# 3. Start the API server and keep it running
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify in another terminal or browser:
```powershell
curl http://127.0.0.1:8000/health
```

## LLM Setup

Life-API uses local models for privacy and cost control:
- **General Model**: Ollama running `llama3.1:8b` (used for Text-to-SQL, summaries, daily insights, query rewriting, and structured JSON).
- **Router Model (optional)**: Needle 3 via `cactus-compute` (used strictly for the ReAct agent's tool selection).

### 1. Install and Start Ollama
Download and install Ollama from [ollama.com](https://ollama.com).

Start the Ollama daemon:
```bash
ollama serve
```

### 2. Pull the General Model
In a separate terminal, pull the required model:
```bash
ollama pull llama3.1:8b
```

Verify that the model is installed and running:
```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

> **IPv4 vs IPv6 Note:** Set `LLM_API_BASE=http://127.0.0.1:11434` in `.env`. On Windows, `localhost` often resolves to the IPv6 loopback `::1` while Ollama listens on IPv4 `127.0.0.1:11434`, resulting in connection timeouts or refusals. Explicitly using `127.0.0.1` ensures reliable direct connectivity.

When Ollama is running and `llama3.1:8b` is pulled, `GET /health` will report `"llm": true`.

## API Examples

```bash
# Health check (no auth)
curl http://localhost:8000/health

# Natural-language query
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What was my average sleep on days I pushed code?"}'

# Hybrid search over notes
curl -X POST http://localhost:8000/v1/search \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"query": "slept badly", "top_k": 5}'

# Daily metrics
curl "http://localhost:8000/v1/metrics?from=2026-10-01&to=2026-10-31&metrics=sleep_hours,commits" \
  -H "X-API-Key: <APP_API_KEY>"
```

## Running Tests

```bash
pytest -q           # all tests (no Ollama required)
pytest -m live -q   # live-LLM tests (needs Ollama running)
ruff check .        # lint
```

## Security Notes

- All LLM-generated SQL is validated by `sqlglot` and executed as a read-only DB role.
- PII is masked before any cloud-model call; never logged raw.
- Default `CLOUD_LLM_ENABLED=false` — data never leaves your machine.

## Build Status

| Phase | Status |
|-------|--------|
| 0 — Scaffold | ✅ |
| 1 — Database | ✅ |
| 2 — Ingestion + Seed | ✅ |
| 3 — Model Gateway + PII | ✅ |
| 4 — Embeddings + Hybrid Search | ✅ |
| 5 — Text-to-SQL | ✅ |
| 6 — Metrics + Insights API | ⬜ |
| 7 — ReAct Agent | ⬜ |
| 8 — Dashboard | ⬜ |
| 9 — Hardening | ⬜ |
