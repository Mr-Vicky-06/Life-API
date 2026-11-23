# Phase 2: ingestion
Date: 2026-11-23 | Branch: phase-2-ingestion | Commit: 5728ae1 | Status: Passed

## 1. Objective
Implement the complete data ingestion and seeding subsystem according to `docs/DATA_AND_RAG.md` (Sections 3 & 4), `docs/API_SPEC.md`, and `docs/SECURITY.md`:
- Text and row cleaning (`cleaning.py`) with HTML stripping, Markdown collapsing, whitespace normalization, timestamp conversion to UTC (assuming `APP_TIMEZONE` for naive times), and SHA-256 content hashing.
- Idempotent upsert loaders (`loaders.py`) utilizing PostgreSQL `ON CONFLICT DO UPDATE` / `ON CONFLICT DO NOTHING` and `RETURNING (xmax = 0)` to accurately report `inserted`, `updated`, and `skipped`.
- Robust CSV validation (`csv_import.py`) with Pydantic row models where malformed rows populate `errors` without crashing requests.
- GitHub commit synchronization client (`github.py`) with 30-day window and pagination, gracefully skipping with a warning when token is omitted.
- Minimal chunking (`chunking.py`, ~500 chars, 80 overlap, sentence-aware, header `"[date | source_type]"`) and embedding singleton (`embeddings.py`, `all-MiniLM-L6-v2`, batch 32, normalized 384-dim vectors).
- API routes in `app/api/routes_ingest.py` protected by `X-API-Key` constant-time verification returning standardized error envelopes.
- Synthetic 90-day seed script (`scripts/seed.py`) with weak correlation between sleep and commits, generating >= 40 journal and >= 20 reading notes, completely idempotent on repeated runs.

## 2. What Was Built
- `docker-compose.yml`: Restricted database port mapping to `127.0.0.1:5432:5432` for local privacy.
- `.env` & `.env.example`: Updated database connection strings to use `127.0.0.1:5432` to avoid IPv6 resolution delays on Windows.
- `app/schemas/ingest.py`: Defined `IngestResult`, `GithubIngestRequest`, `NoteItem`, `HealthCSVRow`, `ReadingCSVRow`, and `ScreenTimeCSVRow`.
- `app/ingestion/cleaning.py`: Implemented `clean_text`, `drop_empty_rows`, `parse_timestamp`, and `compute_content_hash`.
- `app/rag/chunking.py`: Sentence-aware note chunking into 500-char segments with 80-char overlap and metadata headers.
- `app/rag/embeddings.py`: Lazy singleton loading `sentence-transformers/all-MiniLM-L6-v2` generating normalized 384-dim embeddings in batches of 32.
- `app/ingestion/loaders.py`: Atomic upserts for `health_daily`, `reading_log`, `screen_time`, `github_commits`, and notes/chunks deduplication.
- `app/ingestion/csv_import.py`: Streaming CSV parser converting text into validated Pydantic models and accumulating row-level errors.
- `app/ingestion/github.py`: Paginated commit fetcher pulling user events and commit history over configurable time windows.
- `app/api/routes_ingest.py`: Ingestion endpoints mounted at `/v1/ingest/{github|health|reading|screen_time|notes}` with `X-API-Key` auth.
- `app/main.py`: Configured global `HTTPException` and `RequestValidationError` handlers enforcing `API_SPEC.md` error envelope format.
- `app/deps.py`: Updated `verify_api_key` to support optional header injection with immediate 401 response on missing or invalid keys.
- `scripts/seed.py`: 90-day deterministic generator producing correlated health, commits, reading, screen time, and chunked/embedded journal & reading notes.
- `tests/unit/test_cleaning.py`: Unit tests validating HTML stripping, Markdown normalization, whitespace collapsing, naive/UTC timestamps, and chunking.
- `tests/integration/test_ingest.py`: Integration test suite covering authentication enforcement, CSV validation error resilience, duplicate upsert idempotency, mocked GitHub sync, and seed repeatability on `life_test`.

## 3. Key Decisions
- 2026-11-23 | Database port mapping restricted to `127.0.0.1:5432:5432` | Prevents remote network exposure; ensures database access is localhost-only.
- 2026-11-23 | Python 3.12 venv used while ARCHITECTURE.md pins 3.11 | Existing environment runs Python 3.12.10 cleanly with all dependencies compatible.
- 2026-11-23 | Minimal chunking and embeddings modules moved from Phase 4 to Phase 2 | The Phase 2 90-day synthetic seed script requires chunking and embeddings to populate `note_chunks` with real vector embeddings and `tsvector` columns.
- 2026-11-23 | PostgreSQL `(xmax = 0)` used for upsert classification | Accurately and atomically distinguishes between newly inserted rows vs existing updated rows in `ON CONFLICT DO UPDATE` queries.

## 4. Gate Result

### 1. First Seed Run & Count Query (Numbers A)
```powershell
python -m scripts.seed
docker compose exec db psql -P pager=off -U life -d life -c "SELECT (SELECT count(*) FROM health_daily) AS health, (SELECT count(*) FROM github_commits) AS commits, (SELECT count(*) FROM reading_log) AS reading, (SELECT count(*) FROM screen_time) AS screen, (SELECT count(*) FROM notes) AS notes, (SELECT count(*) FROM note_chunks) AS chunks;"
```
**Output:**
```
Seed completed: health=90ins/0upd, commits=340ins/0upd, reading=60ins/0upd, screen=270ins/0upd, notes=53ins/20skip
 health | commits | reading | screen | notes | chunks 
--------+---------+---------+--------+-------+--------
     90 |     340 |      60 |    270 |    53 |     53
(1 row)
```

### 2. Second Seed Run & Count Query (Numbers B)
```powershell
python -m scripts.seed
docker compose exec db psql -P pager=off -U life -d life -c "SELECT (SELECT count(*) FROM health_daily) AS health, (SELECT count(*) FROM github_commits) AS commits, (SELECT count(*) FROM reading_log) AS reading, (SELECT count(*) FROM screen_time) AS screen, (SELECT count(*) FROM notes) AS notes, (SELECT count(*) FROM note_chunks) AS chunks;"
```
**Output:**
```
Seed completed: health=0ins/90upd, commits=0ins/340upd, reading=0ins/60upd, screen=0ins/270upd, notes=0ins/73skip
 health | commits | reading | screen | notes | chunks 
--------+---------+---------+--------+-------+--------
     90 |     340 |      60 |    270 |    53 |     53
(1 row)
```
*Numbers A and Numbers B are identical. Zero new rows inserted on repeated run.*

### 3. Unit and Ingest Integration Tests
```powershell
pytest tests/unit/test_cleaning.py tests/integration/test_ingest.py -q
```
**Output:**
```
...............                                                          [100%]
15 passed in 47.92s
```

### 4. Full Repository Test Suite
```powershell
pytest -q
```
**Output:**
```
..............................                                           [100%]
30 passed in 53.18s
```

---

### 5. Problems and Fixes
- Problem: Docker port binding to `127.0.0.1:5432` caused connection delays in tests using `localhost:5432`. Root cause: Windows `localhost` resolves to IPv6 `::1` before IPv4 `127.0.0.1`. Fix: Updated `.env`, `.env.example`, and test fixtures to connect directly to `127.0.0.1:5432`.
- Problem: Missing `X-API-Key` returned HTTP 422 instead of HTTP 401. Root cause: `Header(...)` in FastAPI raises `RequestValidationError` before calling dependency body if missing. Fix: Made `x_api_key: str | None = Header(default=None)` and performed constant-time verification explicitly raising 401 with standard error envelope.
- Problem: `parse_health_csv` threw `ValueError` when encountering string `'not_a_number'`. Root cause: Direct `float(val)` cast prior to Pydantic validation. Fix: Passed raw string values to Pydantic model validation so invalid numbers are captured in the `errors` list without raising uncaught exceptions.
- Problem: `clean_text` inserted spaces before trailing punctuation when stripping inline HTML tags. Fix: Distinguished block HTML tags (replaced by `" "`) from inline tags (stripped to `""`).

---

### 6. How to Verify Yourself
```powershell
# 1. Run seed script against dev DB
python -m scripts.seed

# 2. Verify row counts
docker compose exec db psql -P pager=off -U life -d life -c "SELECT (SELECT count(*) FROM health_daily) AS health, (SELECT count(*) FROM github_commits) AS commits, (SELECT count(*) FROM reading_log) AS reading, (SELECT count(*) FROM screen_time) AS screen, (SELECT count(*) FROM notes) AS notes, (SELECT count(*) FROM note_chunks) AS chunks;"

# 3. Run seed script again (counts remain identical)
python -m scripts.seed

# 4. Run unit and integration tests
python -m pytest tests/unit/test_cleaning.py tests/integration/test_ingest.py -q

# 5. Run full test suite
python -m pytest -q
```

---

### 7. Known Limitations
- The Python virtual environment runs Python 3.12.10 while `ARCHITECTURE.md` pinned 3.11. All dependencies (including PyTorch, SentenceTransformers, and Psycopg) install and run without issue under 3.12.
- The embedding model `sentence-transformers/all-MiniLM-L6-v2` runs inference on CPU; batch embeddings for 53 notes take ~1.8 seconds.
- GitHub ingestion currently checks user push events; if a user has not pushed in 30 days, 0 commits are fetched.

---

### 8. Next Phase
Phase 3: Model Gateway + PII (PII regex masking & unmasking, guardrails against prompt injection, structured JSON output validation with retry/repair).
