# ARCHITECTURE — Layers, Pinned Stack, Repo Layout

## 1. Layered Design
```
Data Streams (GitHub API | CSV/JSON: health, reading, screen time | notes)
        │
L1  Ingestion & Dataset Pipeline  (fetch → clean → dedupe → UTC → load)
        │   Postgres 16 (+pgvector)
L2  Context Construction: Text-to-SQL | Hybrid Search (FTS + vector, RRF) | Query Rewrite
        │
L3  Model Gateway: LiteLLM wrapper | PII mask/unmask | input/output guardrails | retries
        │
L4  API (FastAPI, Pydantic-enforced JSON)  ──  Streamlit dashboard + ReAct agent
```
Dependency rule: a layer may only import from layers above it in this list (L4 → L3 → L2 → L1). Never upward.

## 2. Pinned Tech Stack (do not add or swap)
| Concern | Choice |
|---|---|
| Language | Python 3.11 |
| API | FastAPI + Uvicorn |
| Validation | Pydantic v2, pydantic-settings |
| DB | PostgreSQL 16 via image `pgvector/pgvector:pg16` (local dev). Neon works by changing `DATABASE_URL` only |
| ORM / migrations | SQLAlchemy 2.x + Alembic, driver `psycopg[binary]` v3 |
| Vector | pgvector (`vector(384)`, HNSW cosine index), Python pkg `pgvector` |
| Embeddings | `sentence-transformers` model `all-MiniLM-L6-v2` (384 dims, runs locally) |
| LLM gateway | `litellm` |
| Local LLM | Ollama (default `LLM_MODEL=ollama/qwen2.5-coder:7b`) |
| Router LLM (optional) | Needle 3 via `cactus-compute` (`ROUTER_MODEL=needle`, approved optional dependency for tool routing only) |
| SQL safety | `sqlglot` |
| HTTP client | `httpx` |
| Dashboard | Streamlit + Plotly |
| Tests | pytest, pytest-asyncio, respx (mock HTTP) |
| Lint | ruff |
| Packaging | `pyproject.toml`, venv. Pin versions with `pip freeze > requirements.lock` after Phase 0 |

### Model Roles
Life-API uses TWO model roles:
1. **GENERAL model** (Ollama, `LLM_MODEL` in `.env`): Text-to-SQL, result summaries, daily insights, query rewriting, structured JSON.
2. **ROUTER model** (Needle, optional, `ROUTER_MODEL` in `.env`): ONLY the ReAct agent's tool selection step. It never writes SQL or prose. Needle is NOT a replacement for the general model.

## 3. Environment Variables (`.env.example`)
```
APP_ENV=dev
APP_API_KEY=change-me
APP_TIMEZONE=Asia/Kolkata
DATABASE_URL=postgresql+psycopg://life:life@localhost:5432/life
DATABASE_URL_RO=postgresql+psycopg://life_ro:life_ro@localhost:5432/life
LLM_MODEL=ollama/qwen2.5-coder:7b
LLM_FALLBACK_MODEL=
LLM_API_BASE=http://127.0.0.1:11434
CLOUD_LLM_ENABLED=false
ROUTER_MODEL=general
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
GITHUB_TOKEN=
GITHUB_USERNAME=
```
If `CLOUD_LLM_ENABLED=false`, the gateway must refuse any non-`ollama/` model.

## 4. Repo Layout (create exactly this)
```
life-api/
├─ ANTIGRAVITY.md  README.md  .env.example  .gitignore
├─ docker-compose.yml  pyproject.toml  alembic.ini
├─ docs/  (PRD, ARCHITECTURE, DATA_AND_RAG, API_SPEC, AGENT_WORKFLOW, SECURITY, TESTING, DECISIONS.md)
├─ migrations/versions/
├─ app/
│  ├─ main.py  config.py  db.py  deps.py
│  ├─ models/        (SQLAlchemy ORM)
│  ├─ schemas/       (Pydantic request/response)
│  ├─ ingestion/     cleaning.py github.py csv_import.py loaders.py
│  ├─ rag/           chunking.py embeddings.py hybrid.py rewrite.py
│  ├─ sql_agent/     schema_prompt.py generator.py validator.py executor.py
│  ├─ gateway/       llm.py pii.py guardrails.py structured.py
│  ├─ agent/         react.py tools.py
│  └─ api/           routes_health.py routes_ingest.py routes_metrics.py
│                    routes_query.py routes_search.py routes_agent.py
├─ dashboard/app.py
├─ scripts/seed.py
└─ tests/  (unit/, integration/, security/, golden/)
```

## 4b. Docker Compose
Single service `db` (image above), env `POSTGRES_USER=life POSTGRES_PASSWORD=life POSTGRES_DB=life`, port 5432, named volume, healthcheck `pg_isready`. An init SQL mounted at `/docker-entrypoint-initdb.d/` creates extension `vector` and role `life_ro` (password `life_ro`, `LOGIN`, no create/write). Migrations grant `SELECT` on allowlisted views to `life_ro`.

## 5. Key Design Decisions (fixed)
| Topic | Decision |
|---|---|
| Term-based search | Postgres FTS (`tsvector` + `ts_rank_cd`), not BM25 |
| Fusion | Reciprocal Rank Fusion, `k=60`, top 20 per leg → return top 8 |
| Chunking | 500 chars, 80 overlap, prepend `[date | source_type]` header |
| Time handling | Store UTC; `date` columns are the owner's local date |
| Integrations | GitHub live; health/reading/screen time via CSV/JSON (no OAuth) |
| Agent | Hand-written ReAct loop (no LangChain/LlamaIndex), max 5 steps |
| Auth | Header `X-API-Key` equals `APP_API_KEY`, on every `/v1/*` route |
