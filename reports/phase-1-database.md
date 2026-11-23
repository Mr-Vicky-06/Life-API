# Phase 1: database
Date: 2026-11-23 | Branch: phase-1-database | Commit: 7702e5f | Status: Passed

## 1. Objective
Set up the complete PostgreSQL 16 + pgvector database foundation for Life-API according to `docs/DATA_AND_RAG.md` and `docs/SECURITY.md`:
- SQLAlchemy 2.x ORM models for all 7 tables (`health_daily`, `github_commits`, `reading_log`, `screen_time`, `notes`, `note_chunks`, `query_log`) with exact column types, foreign keys, cascade rules, and check constraints.
- Alembic configuration and migration `0001_init` establishing the `vector` extension, tables, GIN index on tsvector, HNSW index on embeddings, the 4 allowlisted views (`v_daily_summary`, `v_commits`, `v_screen_time`, `v_reading`), and `GRANT SELECT` on only those views to `life_ro`.
- Dual SQLAlchemy engine setup in `app/db.py`: RW (`life` user) and RO (`life_ro` user), with RO sessions enforced read-only at both connection options (`default_transaction_read_only=on`) and transaction levels (`SET TRANSACTION READ ONLY`).
- Live `/health` endpoint verification where `db: true` requires an actual `SELECT 1` execution.
- Comprehensive integration tests in `tests/integration/test_db.py` running in an isolated `life_test` database.

## 2. What Was Built
- `.gitignore`: Fixed `/models/` pattern anchoring to prevent accidental exclusion of the `app/models/` package.
- `app/models/`:
  - `health.py`: `HealthDaily` mapping daily sleep, HRV, resting HR, and activity metrics.
  - `commits.py`: `GithubCommit` mapping commit SHAs, author dates, repos, additions, and deletions.
  - `reading.py`: `ReadingLog` mapping book titles, reading minutes, and pages read with `UNIQUE (date, title)`.
  - `screen_time.py`: `ScreenTime` mapping composite primary key `(date, category)` and usage minutes.
  - `notes.py`: `Note` and `NoteChunk` mapping journal/reading/commit notes with cascading chunks, pgvector `Vector(384)`, stored generated `tsvector`, and HNSW/GIN indexes.
  - `query_log.py`: `QueryLog` tracking Text-to-SQL query audits, masked prompts, latency, and status.
  - `__init__.py`: Package export registering all models on `Base.metadata`.
- `docker/init.sql`: Extended container initialization to grant schema usage and connect permissions to `life_ro`.
- `alembic.ini`: Added `path_separator = os` to eliminate configuration deprecation warnings.
- `migrations/env.py`: Configured to resolve `DATABASE_URL` dynamically from `app.config.get_settings()` and bind `app.models`.
- `migrations/versions/0001_init.py`: Full DDL migration for `vector` extension, all 7 tables, GIN/HNSW indexes, idempotent `life_ro` role creation, 4 allowlisted views, and explicit `GRANT SELECT` to `life_ro`. Includes a clean `downgrade()` implementation.
- `app/db.py`: Dual engines (`_rw_engine` and `_ro_engine`), connection pooling, read-only session dependency enforcing transaction constraints, engine reset helper for tests, and live `check_db()` executing `SELECT 1`.
- `tests/integration/test_db.py`: 5 automated tests verifying empty DB upgrade, downgrade/upgrade cycle, view read access for `life_ro`, denial of inserts and base table access for `life_ro`, and `note_chunks` vector storage with automatic `tsv` generation.

## 3. Key Decisions
- 2026-11-23 | RO Engine sets `options="-c default_transaction_read_only=on"` in addition to `SET TRANSACTION READ ONLY` | Defense in depth ensures any statement executed via the read-only engine cannot mutate the database even if user credentials had write grants.
- 2026-11-23 | `NoteChunk.chunk_metadata` maps to DB column `"metadata"` | SQLAlchemy declarative models reserve `Model.metadata` for `MetaData`. Mapping the attribute to `chunk_metadata` while preserving the `"metadata"` DB column name prevents namespace collision.
- 2026-11-23 | Integration tests run against isolated `life_test` database via fixture | The dev database `life` remains untouched during test runs.

## 4. Gate Result
Commands run and outputs:

1. `docker compose ps`
```
NAME            IMAGE                    COMMAND                  SERVICE   CREATED         STATUS                   PORTS
life_api-db-1   pgvector/pgvector:pg16   "docker-entrypoint.s…"   db        8 minutes ago   Up 8 minutes (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
```

2. `alembic upgrade head`
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

3. `alembic downgrade base && alembic upgrade head`
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 0001_init -> , Initial migration: pgvector, tables, indexes, views, and life_ro role grants.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_init, Initial migration: pgvector, tables, indexes, views, and life_ro role grants.
```

4. `pytest tests/integration/test_db.py -q`
```
.....                                                                    [100%]
5 passed in 2.04s
```

5. `pytest -q`
```
...............                                                          [100%]
15 passed in 3.62s
```

6. `curl.exe -s http://127.0.0.1:8000/health`
```json
{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"none"}
```

## 5. Problems and Fixes
- Problem: `docker` command failed with `CommandNotFoundException` in PowerShell. Root cause: Docker Desktop was installed under the user profile (`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`), and the IDE process environment PATH had not reloaded registry changes. Fix: Refreshed PATH to merge Machine and User paths; Docker 29.9.3 and Compose v5.7.0 verified.
- Problem: `git status` did not detect new files created under `app/models/`. Root cause: Root `.gitignore` had `models/` which matched any folder named `models/` anywhere in the tree. Fix: Changed rule to `/models/` anchored to root.
- Problem: SQLAlchemy warned that attribute name `metadata` is reserved for the `MetaData` collection on DeclarativeBase classes. Root cause: Column name in DB schema is `metadata jsonb`. Fix: Defined the ORM attribute as `chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, ...)`.
- Problem: Alembic emitted deprecation warning regarding `prepend_sys_path` without `path_separator`. Fix: Added `path_separator = os` to `alembic.ini`.

## 6. How to Verify Yourself
```powershell
# 1. Ensure Docker db container is running
docker compose ps

# 2. Run Alembic migrations
python -m alembic upgrade head

# 3. Test migration downgrade and upgrade
python -m alembic downgrade base
python -m alembic upgrade head

# 4. Run integration tests (runs on isolated life_test DB)
python -m pytest tests/integration/test_db.py -q

# 5. Run all tests
python -m pytest -q

# 6. Verify health endpoint reports db:true and llm:true
curl.exe -s http://127.0.0.1:8000/health
```

## 7. Known Limitations
- The database tables are unpopulated until Phase 2 ingestion pipelines and seed scripts are implemented.
- Full hybrid search querying will be wired up in Phase 4 (pgvector and tsvector columns are validated at schema level).

## 8. Next Phase
Phase 2: Ingestion & Seed (data ingestion endpoints for GitHub, Health, Reading, Screen time, Notes, chunking & embedding pipeline, and synthetic 90-day seed script).
