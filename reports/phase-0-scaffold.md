# Phase 0: scaffold
Date: 2026-11-22 | Branch: phase-0-scaffold | Commit: cd50d18 | Status: Passed

## 1. Objective
Create repo layout, `pyproject.toml`, `.env.example`, `.gitignore` (include `.env`), `docker-compose.yml`, `README.md`, FastAPI app with `/health`, config via pydantic-settings, and virtual environment installation. Verify that `/health` returns `{"status":"ok",...}` and smoke test passes.

## 2. What Was Built
- `pyproject.toml`: Project metadata, pinned dependency specifications, and tool configs for pytest and ruff.
- `docker-compose.yml`: Postgres 16 service using `pgvector/pgvector:pg16` with healthcheck.
- `docker/init.sql`: Entrypoint initialization script creating the `vector` extension and `life_ro` login role.
- `alembic.ini`: Migration configuration file configured to use dynamic database connection URLs.
- `migrations/env.py`: Migration environment runner configuring SQLAlchemy engines from environment variables.
- `migrations/script.py.mako`: Migration script template for Alembic version files.
- `app/config.py`: Pydantic-settings configuration model loading all variables from `.env`.
- `app/db.py`: SQLAlchemy engine factory with read-write/read-only connection pooling and `check_db` utility.
- `app/deps.py`: Constant-time API key authentication dependency and session dependencies.
- `app/main.py`: FastAPI application entry point with CORS, in-memory rate limiting (60 req/min), and health route mounting.
- `app/api/routes_health.py`: Unauthenticated `GET /health` endpoint reporting system and database status.
- `tests/test_smoke.py`: Smoke test validating `GET /health` structure and route protection.
- `tests/conftest.py`: Test environment setup fixture and reusable TestClient fixture.
- `README.md`: Project documentation covering architecture, quickstart, API curl examples, and build status tracker.

## 3. Key Decisions
- 2026-11-22 | Docker init SQL (`/docker-entrypoint-initdb.d/`) creates `vector` extension and `life_ro` role only; `GRANT SELECT ON views TO life_ro` lives in the Alembic migration (`0001_init`), not in init SQL | Views don't exist until migrations run; granting in init SQL would silently fail. ARCHITECTURE §4b and DATA_AND_RAG §2 imply this split; making it explicit.
- 2026-11-22 | `SearchHit.note_id` is the parent note FK (`note_chunks.note_id`), not the chunk PK | DATA_AND_RAG §5 lists note_date/source_type/snippet but not which ID; API_SPEC uses `note_id`; using the parent note FK is most useful to callers wanting to fetch the full note.
- 2026-11-22 | PII masking applies to outbound payload only when model is not `ollama/*`; log-level redaction is always-on regardless of model | SECURITY §2 and AGENT_WORKFLOW Part B both say cloud-only payload masking; SECURITY §5 says always redact in logs. No conflict — two separate code paths. Noted for implementor clarity.

## 4. Gate Result
Command: `uvicorn app.main:app --port 8000 & curl http://localhost:8000/health && pytest -q`
Output:
```
CURL_OUTPUT: {"status":"ok","db":false,"llm":false}
..                                                                       [100%]
2 passed in 6.16s
```

## 5. Problems and Fixes
- Problem: `pip install -e ".[dev]"` failed with `BackendUnavailable: Cannot import 'setuptools.backends.legacy'`. Root cause: `build-backend` in `pyproject.toml` had an outdated backend string. Fix: changed build backend to `setuptools.build_meta` and added wheel/setuptools build requirements.
- Problem: Pip editable build reported package discovery failure. Root cause: setuptools requires package discovery configuration when multiple top-level packages exist. Fix: added `[tool.setuptools.packages.find]` specifying `where = ["."]` and including app, dashboard, scripts, migrations.
- Problem: `check_db()` in `app/db.py` hung indefinitely when connecting to `localhost:5432` without a running database service. Root cause: psycopg default TCP connection timeout on Windows waits for OS TCP SYN retransmission timeout across IPv6 and IPv4. Fix: added `connect_args={"connect_timeout": 2}` to engine configuration so connection attempts fail fast with `ConnectionTimeout`.
- Problem: `http://localhost:8000/health` showed `ERR_CONNECTION_REFUSED` in browser after gate run. Root cause: Uvicorn was stopped immediately after synchronous gate validation finished, leaving no server listening on port 8000. Fix: Started background Uvicorn daemon bound to `127.0.0.1:8000`, verified with `curl http://127.0.0.1:8000/health` returning `{"status":"ok","db":false,"llm":false}`, added `scripts/dev.ps1` helper script, added `tests/test_health.py`, and updated README.md with run instructions.

## 6. How to Verify Yourself
```powershell
# 1. Activate venv
.\.venv\Scripts\Activate.ps1

# 2. Run the smoke test suite
python -m pytest -q

# 3. Start Uvicorn in one terminal
python -m uvicorn app.main:app --port 8000

# 4. In another terminal, verify the health endpoint
curl http://localhost:8000/health
```

## 7. Known Limitations
- Database service is not running locally yet; `/health` reports `"db": false` until Postgres is started and migrated in Phase 1.
- Docker CLI is not installed on the Windows host PATH; Phase 1 will require starting PostgreSQL 16 with pgvector (via local service or remote instance specified by `DATABASE_URL`).

## 8. Next Phase
Phase 1: Database (ORM models, Alembic `0001_init` migration for tables, views, indexes, and read-only grants).
