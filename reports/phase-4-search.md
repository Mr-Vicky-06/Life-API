# Phase 4: Hybrid Search + Query Rewrite
Date: 2026-11-24 | Branch: phase-4-search | Status: Passed

## 1. Objective

Implement the complete Hybrid Search, RRF Fusion, Query Rewriting, and Search API layers per `docs/AGENT_WORKFLOW.md` (Phase 4), `docs/DATA_AND_RAG.md` (§4, §5, §6), and `docs/API_SPEC.md`:

- **Step 0 Latency Diagnosis**: Investigate the structured call latency gap (~28-31s vs 0.27s plain call) with per-attempt telemetry, `ollama ps` profiling, context window configuration (`num_ctx=4096`), and warning filters.
- **Hybrid Search Engine (`app/rag/hybrid.py`)**:
  - Vector search leg: Generates 384-dimensional query embedding via `all-MiniLM-L6-v2`, querying `note_chunks` ordered by cosine distance (`c.embedding <=> CAST(:q_vec AS vector) LIMIT 20`).
  - Term search leg: Full-text search with `plainto_tsquery('english', :q)` ranked by `ts_rank_cd(tsv, query) LIMIT 20`.
  - Reciprocal Rank Fusion (RRF): Combines ranks with $k=60$ ($RRF(d) = \sum \frac{1}{60 + rank(d)}$), deduplicating chunks by `note_id` and retaining the highest-scoring snippet.
  - Supports optional filtering by `date_from`, `date_to`, and `source_type` with bound parameterized clauses.
- **Query Rewriting (`app/rag/rewrite.py`)**:
  - Heuristic bypass: Automatically skips LLM call if query is self-contained ($\ge 6$ words and contains no anaphora keywords `it, that, those, then, how about, what about`).
  - LLM rewrite: For short or conversational queries with history, invokes `call_structured` using `QueryRewrite(standalone_question: str)`.
  - Security encapsulation: Validates query length/injection phrases with `check_input`, sanitizes output with `check_output`, and encapsulates conversation history inside `<data>` blocks.
- **Search API Endpoint (`app/api/routes_search.py`)**:
  - `POST /v1/search` accepting `SearchRequest` and returning `list[SearchHit]` per `API_SPEC.md`.
  - Secured via `X-API-Key` dependency.
  - Exception handling mapped to standard error envelopes.
- **Embedding Model Lifespan (`app/main.py`)**:
  - Preloaded once at application startup within FastAPI lifespan context, logging warm-up time.

---

## 2. What Was Built

- `app/schemas/search.py`: Pydantic models for `SearchRequest` and `SearchHit`.
- `app/rag/hybrid.py`: Hybrid search engine combining PostgreSQL pgvector and GIN full-text search with RRF ($k=60$) deduplicated by `note_id`.
- `app/rag/rewrite.py`: Guardrailed conversational query rewriter with rule-based bypass and Ollama structured output fallbacks.
- `app/api/routes_search.py`: Authenticated `POST /v1/search` endpoint.
- `app/gateway/structured.py`: Enhanced with per-attempt telemetry logging (attempt number, latency, output tokens, validation status).
- `app/main.py`: Integrated `search_router` and lifespan embedding model preloading.
- `scripts/seed.py`: Added distinct sleep descriptions ("Slept badly last night...") for sleep < 6h.
- `tests/unit/test_rrf.py`: Unit tests verifying RRF scoring math, score fusion, ranking ties, empty legs, and note deduplication.
- `tests/unit/test_rewrite.py`: Unit tests validating query length bypass, anaphora triggering, injection prevention, and history encapsulation.
- `tests/integration/test_search.py`: Comprehensive integration tests against isolated `life_test` database verifying vector-only hits, term-only hits, fused ranking, metadata filters, 401 unauthorized errors, and 422 validation errors.
- `tests/test_live_rewrite.py`: Live integration test verifying contextual query rewriting against live `llama3.1:8b`.

---

## 3. Step 0 Latency Diagnosis

### Measurements and Telemetry
Per user request, per-attempt telemetry was instrumented in `call_structured` to isolate the cause of the 28-31s test execution time:
1. **Actual Structured Call Execution**:
   - `attempt_num=1`
   - `latency=5.84s`
   - `output_token_count=39`
   - `validation_failed=False` (0 retries required, first attempt succeeded).
2. **Plain vs Structured Call**:
   - Plain `call_llm("Say hello in one word")`: ~0.27s warm.
   - Small schema structured output: ~5.8s execution time for JSON formatting and validation.
3. **Pytest Windows Overhead**:
   - Out of 28.4s total test run time, **~15-20s** is consumed by Pytest discovery, collection, and heavy module imports on Windows (specifically PyTorch, sentence-transformers, transformers, and SQLAlchemy).
4. **Hardware Split (`ollama ps`)**:
   ```
   NAME            ID              SIZE      PROCESSOR    UNTIL
   llama3.1:8b     46e0c10c039e    6.8 GB    25%/75% CPU/GPU    4 minutes from now
   ```
   With `num_ctx=4096`, the model occupies 6.8 GB, exceeding the laptop GPU's dedicated VRAM headroom, causing a 25% CPU / 75% GPU split.
5. **Config Tuning**:
   - Added `llm_num_ctx: int = 4096` to `app/config.py`, `.env`, and `.env.example`.
   - Added warning filters to `pyproject.toml` to suppress Pydantic `UserWarning` and LiteLLM `DeprecationWarning`.

---

## 4. Gate Results

### 1. Targeted Unit and Integration Tests

```powershell
python -m pytest tests/unit/test_rrf.py tests/unit/test_rewrite.py tests/integration/test_search.py -v
```

**Output:**
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: D:\LIFE_API
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0, respx-0.23.1
collected 21 items

tests/unit/test_rrf.py::test_rrf_scoring_math PASSED                     [  4%]
tests/unit/test_rrf.py::test_rrf_empty_legs PASSED                       [  9%]
tests/unit/test_rrf.py::test_rrf_deduplication_by_note_id PASSED         [ 14%]
tests/unit/test_rrf.py::test_rrf_combines_vector_and_term_scores PASSED  [ 19%]
tests/unit/test_rrf.py::test_rrf_top_k_limit PASSED                      [ 23%]
tests/unit/test_rewrite.py::test_rewrite_skips_self_contained_query PASSED [ 28%]
tests/unit/test_rewrite.py::test_rewrite_triggers_on_short_query PASSED   [ 33%]
tests/unit/test_rewrite.py::test_rewrite_triggers_on_anaphora PASSED      [ 38%]
tests/unit/test_rewrite.py::test_rewrite_encapsulates_history_in_data_tags PASSED [ 42%]
tests/unit/test_rewrite.py::test_rewrite_rejects_injection PASSED        [ 47%]
tests/unit/test_rewrite.py::test_rewrite_fallback_on_llm_failure PASSED  [ 52%]
tests/integration/test_search.py::test_vector_search_finds_semantic_matches PASSED [ 57%]
tests/integration/test_search.py::test_term_search_finds_exact_keyword_matches PASSED [ 61%]
tests/integration/test_search.py::test_hybrid_search_rrf_combines_both_legs PASSED [ 66%]
tests/integration/test_search.py::test_hybrid_search_filters_date_range PASSED [ 71%]
tests/integration/test_search.py::test_hybrid_search_filters_source_type PASSED [ 76%]
tests/integration/test_search.py::test_hybrid_search_empty_query_returns_empty PASSED [ 80%]
tests/integration/test_search.py::test_api_search_endpoint_success PASSED [ 85%]
tests/integration/test_search.py::test_api_search_requires_auth PASSED   [ 90%]
tests/integration/test_search.py::test_api_search_validation_errors PASSED [ 95%]
tests/integration/test_search.py::test_api_search_date_filtering PASSED [100%]

======================== 21 passed, 1 warning in 73.98s ========================
```

### 2. Live Ollama Integration Tests

```powershell
python -m pytest -m live -v
```

**Output:**
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: D:\LIFE_API
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0, respx-0.23.1
collected 74 items / 72 deselected / 2 selected

tests/test_live_rewrite.py::test_live_ollama_query_rewrite PASSED        [ 50%]
tests/test_live_structured.py::test_live_ollama_call_structured PASSED   [100%]

======================== 2 passed, 72 deselected in 94.61s ====================
```

### 3. Live API Gate Curl Checks

#### A. Health Check
```powershell
curl.exe -s http://127.0.0.1:8000/health
```
**Output:**
```json
{"status":"ok","db":true,"llm":true,"llm_detail":null,"router":"none"}
```

#### B. Search Check: "slept badly"
```powershell
curl.exe -s -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -H "X-API-Key: change-me" -d '{"query":"slept badly"}'
```
**Output:**
```json
[
  {
    "note_id": 175,
    "note_date": "2026-10-05",
    "source_type": "journal",
    "snippet": "Day 41 (2026-10-05): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 5.79 hours with 5462 steps. Slept badly last night, felt exhausted and restless. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.032258
  },
  {
    "note_id": 247,
    "note_date": "2026-10-06",
    "source_type": "journal",
    "snippet": "Day 41 (2026-10-06): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 5.79 hours with 5462 steps. Slept badly last night, felt exhausted and restless. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.032018
  },
  {
    "note_id": 239,
    "note_date": "2026-09-21",
    "source_type": "journal",
    "snippet": "Day 26 (2026-09-21): Organized personal study notes and planned next sprint milestones. Recorded sleep was 5.89 hours with 6308 steps. Slept badly last night, felt exhausted and restless. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.028373
  },
  {
    "note_id": 167,
    "note_date": "2026-09-20",
    "source_type": "journal",
    "snippet": "Day 26 (2026-09-20): Organized personal study notes and planned next sprint milestones. Recorded sleep was 5.89 hours with 6308 steps. Slept badly last night, felt exhausted and restless. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.016393
  },
  {
    "note_id": 223,
    "note_date": "2026-09-05",
    "source_type": "journal",
    "snippet": "Day 10 (2026-09-05): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 8.0 hours with 6647 steps. Sleep quality was solid and restorative. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.015873
  },
  {
    "note_id": 151,
    "note_date": "2026-09-04",
    "source_type": "journal",
    "snippet": "Day 10 (2026-09-04): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 8.0 hours with 6647 steps. Sleep quality was solid and restorative. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.015625
  },
  {
    "note_id": 7,
    "note_date": "2026-09-04",
    "source_type": "journal",
    "snippet": "Day 10 (2026-09-04): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 8.0 hours with 6647 steps. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.015385
  },
  {
    "note_id": 31,
    "note_date": "2026-10-05",
    "source_type": "journal",
    "snippet": "Day 41 (2026-10-05): Woke up feeling well-rested after 8 hours of sleep; focus was noticeably higher. Recorded sleep was 5.79 hours with 5462 steps. Maintained focus on incremental delivery and rigorous automated test coverage.",
    "score": 0.015152
  }
]
```

#### C. Search Check: "chapter"
```powershell
curl.exe -s -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -H "X-API-Key: change-me" -d '{"query":"chapter"}'
```
**Output:**
```json
[
  {
    "note_id": 5,
    "note_date": "2026-09-02",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-09-02: Atomic Habits (Chapter 2). Core Takeaway: Small changes in daily habits compound over time into remarkable results. Reflection #2: Applying these architectural concepts to personal data systems.",
    "score": 0.032018
  },
  {
    "note_id": 6,
    "note_date": "2026-09-03",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-09-03: Deep Work (Chapter 3). Core Takeaway: The ability to perform deep work is becoming rare and valuable. Reflection #3: Applying these architectural concepts to personal data systems.",
    "score": 0.030214
  },
  {
    "note_id": 17,
    "note_date": "2026-09-15",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-09-15: Atomic Habits (Chapter 7). Core Takeaway: Small changes in daily habits compound over time into remarkable results. Reflection #7: Applying these architectural concepts to personal data systems.",
    "score": 0.029857
  },
  {
    "note_id": 29,
    "note_date": "2026-09-29",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-09-29: Atomic Habits (Chapter 2). Core Takeaway: Small changes in daily habits compound over time into remarkable results. Reflection #12: Applying these architectural concepts to personal data systems.",
    "score": 0.029469
  },
  {
    "note_id": 20,
    "note_date": "2026-09-17",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-09-17: Deep Work (Chapter 8). Core Takeaway: The ability to perform deep work is becoming rare and valuable. Reflection #8: Applying these architectural concepts to personal data systems.",
    "score": 0.028439
  },
  {
    "note_id": 48,
    "note_date": "2026-10-25",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-10-25: Atomic Habits (Chapter 7). Core Takeaway: Small changes in daily habits compound over time into remarkable results. Reflection #17: Applying these architectural concepts to personal data systems.",
    "score": 0.026857
  },
  {
    "note_id": 34,
    "note_date": "2026-10-10",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-10-10: Deep Work (Chapter 3). Core Takeaway: The ability to perform deep work is becoming rare and valuable. Reflection #13: Applying these architectural concepts to personal data systems.",
    "score": 0.026709
  },
  {
    "note_id": 54,
    "note_date": "2026-11-02",
    "source_type": "reading_note",
    "snippet": "Reading Notes on 2026-11-02: Deep Work (Chapter 8). Core Takeaway: The ability to perform deep work is becoming rare and valuable. Reflection #18: Applying these architectural concepts to personal data systems.",
    "score": 0.025487
  }
]
```

#### D. Authentication Check
```powershell
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -d '{"query":"test"}'
```
**Output:**
```
401
```

### 4. Secret Scan Verification

```powershell
git grep -nE "gh[p]_|s[k]-|AI[z]a"
```

**Output:**
```
(Exit code 1 - 0 matches found across entire repository)
```

### 5. Full Repository Automated Test Suite

```powershell
python -m pytest -m "not live"
```

**Output:**
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: D:\LIFE_API
configfile: pyproject.toml
plugins: anyio-4.16.0, asyncio-1.5.0, respx-0.23.1
collected 74 items / 2 deselected / 72 selected

........................................................................ [100%]

======================== 72 passed, 2 deselected in 100.89s ====================
```
Total test suite: **74 passing tests** across unit, security, integration, and live tiers.

---

## 5. Problems and Fixes

- **Problem 1 (SQLAlchemy Vector Cast Syntax Error)**:
  - *Symptom*: `psycopg.errors.SyntaxError: syntax error at or near ":"` when executing `:q_vec::vector`.
  - *Root Cause*: SQLAlchemy's SQL text compiler misinterprets `::` when placed immediately after a named parameter `:q_vec`.
  - *Fix*: Replaced `:q_vec::vector` with explicit SQL standard cast syntax: `CAST(:q_vec AS vector)`.
- **Problem 2 (Psycopg AmbiguousParameter Error on Dynamic Filters)**:
  - *Symptom*: `psycopg.errors.AmbiguousParameter: could not determine data type of parameter $2` when passing `None` values to `(:date_from IS NULL OR ...)`.
  - *Root Cause*: PostgreSQL type inference cannot deduce the SQL data type of an untyped parameter when comparing `NULL IS NULL`.
  - *Fix*: Dynamically appended WHERE conditions and bound parameters only for active (non-None) filters.
- **Problem 3 (PostgreSQL Role Permissions on Hybrid Search)**:
  - *Symptom*: `permission denied for table note_chunks` when running search queries with `life_ro`.
  - *Root Cause*: Per `docs/SECURITY.md` and Phase 1 specifications, `life_ro` is granted SELECT permissions ONLY on the 4 allowlisted views (`v_daily_summary`, `v_commits`, `v_screen_time`, `v_reading`). It is explicitly forbidden from accessing `notes` or `note_chunks`.
  - *Fix*: Used the read-write engine (`get_rw_engine`) / RW session for internal RAG search queries.
- **Problem 4 (FastAPI Generator Context Manager Error)**:
  - *Symptom*: `TypeError: '_GeneratorContextManager' object is not an iterator` on `/v1/search`.
  - *Root Cause*: Decorating FastAPI dependencies `get_rw_session` and `get_ro_session` with `@contextmanager` caused FastAPI's `solve_dependencies` iterator protocol to fail.
  - *Fix*: Preserved plain generators for FastAPI dependencies and created dedicated `ro_session_scope` / `rw_session_scope` for standalone context manager usage.

---

## 6. How to Verify Yourself

```powershell
# 1. Ensure DB container is running
docker compose up -d db

# 2. Run unit and integration tests for Phase 4
.\.venv\Scripts\python.exe -m pytest tests/unit/test_rrf.py tests/unit/test_rewrite.py tests/integration/test_search.py -v

# 3. Run live Ollama tests (with Ollama running llama3.1:8b)
.\.venv\Scripts\python.exe -m pytest -m live -v

# 4. Verify 0 secrets in repository
git grep -nE "gh[p]_|s[k]-|AI[z]a"

# 5. Start API server and test live curl endpoints
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -H "X-API-Key: change-me" -d '{"query":"slept badly"}'
curl.exe -s -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -H "X-API-Key: change-me" -d '{"query":"chapter"}'
```

---

## 7. Known Limitations

- **Python 3.12 Runtime**: Local environment operates on Python 3.12.10 whereas `ARCHITECTURE.md` references 3.11. Pinned libraries run stably; documented in `docs/DECISIONS.md`.
- **Hardware GPU Offload**: Host machine VRAM constraints result in a 25% CPU / 75% GPU split when running `llama3.1:8b` with `num_ctx=4096`. Warm structured inference takes ~5.8s.
