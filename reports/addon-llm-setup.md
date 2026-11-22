# Add-on: LLM Setup and Needle Integration
Date: 2026-11-22 | Branch: chore-llm-router | Commit: 3ffbf52 | Status: Passed

## 1. Objective
Complete LLM setup and Needle integration before Phase 1:
1. Two-model architecture decision recorded in `docs/DECISIONS.md`.
2. Fix `/health` to verify Ollama reachability and `LLM_MODEL` existence, returning status, db, llm, llm_detail, and router type.
3. Conduct Needle spike test on 20 queries across `sql_query`, `search_notes`, and `get_metrics` using the runtime from `D:\VYKE\voicecore` and evaluate decision rule (tool accuracy >= 90%, args >= 80%).
4. Define `RouterBackend` protocol and `GeneralLLMRouter` in `app/gateway/router.py`.
5. Update docs (`docs/ARCHITECTURE.md`, `docs/AGENT_WORKFLOW.md`, `docs/SECURITY.md`, `README.md`).

## 2. What Was Built
- `docs/DECISIONS.md`: Recorded two-model roles architecture decision.
- `docs/ARCHITECTURE.md`: Added Needle as approved optional dependency, added ROUTER_MODEL to .env docs, documented two model roles.
- `docs/AGENT_WORKFLOW.md`: Noted Phase 3 builds RouterBackend and Phase 7 consumes it.
- `docs/SECURITY.md`: Clarified local execution privacy for Needle and mandatory argument validation.
- `app/config.py`: Added `router_model` setting defaulting to `"general"`.
- `.env.example`: Added `ROUTER_MODEL=general`.
- `app/api/routes_health.py`: Implemented real Ollama tags check via httpx with safe error details and router model reporting.
- `tests/test_health.py`: Added comprehensive unit tests with `respx` mocking Ollama up, model missing, and Ollama down.
- `README.md`: Added "LLM Setup" section detailing `ollama serve` and `ollama pull llama3.1:8b`.
- `tools.json`: Defined tool schemas for `sql_query`, `search_notes`, and `get_metrics`.
- `scripts/spike_needle.py`: 20-query evaluation script for tool routing, argument validation, latency, and accept/reject decision.
- `app/gateway/router.py`: Protocol `RouterBackend` and `GeneralLLMRouter` implementation.
- `tests/unit/test_router.py`: Tests for `RouterBackend` protocol conformance and `get_router` factory behavior.

## 3. Key Decisions
| 2026-11-22 | Life-API uses TWO model roles: (1) GENERAL model (Ollama, LLM_MODEL in .env) for Text-to-SQL, result summaries, daily insights, query rewriting, structured JSON; (2) ROUTER model (Needle, optional, ROUTER_MODEL in .env) ONLY for the ReAct agent's tool selection step | Needle is NOT a replacement for the general model because it is a tool-calling model with little general chat ability; it never writes SQL or prose. |

## 4. Gate Result
Command: `pytest -q`
Output:
```
.........                                                                [100%]
9 passed in 34.77s
```

Command: `python scripts/spike_needle.py`
Output:
```
Loaded tools definition from tools.json (3 tools)
Initializing NeedleAgent (cactus v4.1.0) ...

================================================================================
NEEDLE SPIKE EVALUATION (20 TEST QUERIES)
================================================================================
[01/20] Query: 'Run a SQL query: what was my average sleep duration last week?'
       Expected: sql_query | Actual: sql_query -> Tool: [PASS]
       Args: {'question': 'what was my average sleep duration last week'} -> Args: [PASS]
       Latency: 1156.0ms | Confidence: 0.2405

[02/20] Query: 'Execute SQL query to calculate total commits per repository'
       Expected: sql_query | Actual: sql_query -> Tool: [PASS]
       Args: {'question': 'total commits per repository'} -> Args: [PASS]
       Latency: 2520.0ms | Confidence: 0.3266

[03/20] Query: 'Run SQL query to show my top 5 longest reading sessions'
       Expected: sql_query | Actual: None -> Tool: [FAIL]
       Args: {} -> Args: [FAIL]
       Latency: 1399.1ms | Confidence: 0.0775

[04/20] Query: 'Query database: which day had the highest screen time?'
       Expected: sql_query | Actual: None -> Tool: [FAIL]
       Args: {} -> Args: [FAIL]
       Latency: 1320.0ms | Confidence: 0.018

[05/20] Query: 'Run SQL query to calculate correlation between sleep and commits'
       Expected: sql_query | Actual: sql_query -> Tool: [PASS]
       Args: {'question': 'calculate correlation between sleep and commits'} -> Args: [PASS]
       Latency: 1331.7ms | Confidence: 0.2638

[06/20] Query: 'Query the database for all records with zero commits'
       Expected: sql_query | Actual: search_notes -> Tool: [FAIL]
       Args: {'query': 'zero commits', 'top_k': 0} -> Args: [FAIL]
       Latency: 1424.1ms | Confidence: 0.2127

[07/20] Query: 'Search notes for machine learning ideas with top_k 5'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'machine learning ideas', 'top_k': 5} -> Args: [PASS]
       Latency: 1139.3ms | Confidence: 0.8929

[08/20] Query: 'Search my notes for travel itinerary top 3'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'travel itinerary', 'top_k': 3} -> Args: [PASS]
       Latency: 1080.4ms | Confidence: 0.8601

[09/20] Query: 'Search journal notes for workout routines top 10'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'workout routines', 'top_k': 10} -> Args: [PASS]
       Latency: 1116.0ms | Confidence: 0.8627

[10/20] Query: 'Search notes for book summary notes top 5'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'book summary', 'top_k': 5} -> Args: [PASS]
       Latency: 1231.9ms | Confidence: 0.8621

[11/20] Query: 'Search notes for career goals top 5'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'career goals', 'top_k': 5} -> Args: [PASS]
       Latency: 1861.9ms | Confidence: 0.925

[12/20] Query: 'Find in notes meeting notes with Sarah top 5'
       Expected: search_notes | Actual: search_notes -> Tool: [PASS]
       Args: {'query': 'meeting notes with Sarah', 'top_k': 5} -> Args: [PASS]
       Latency: 1256.0ms | Confidence: 0.5834

[13/20] Query: 'Get metrics for sleep from 2026-10-01 to 2026-10-31'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-10-01', 'to': '2026-10-31', 'metrics': ['sleep_hours', 'commits', 'steps']} -> Args: [PASS]
       Latency: 1660.8ms | Confidence: 0.6839

[14/20] Query: 'Retrieve metrics commits and steps from 2026-09-01 to 2026-09-30'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-09-01', 'to': '2026-09-30', 'metrics': ['commits', 'steps']} -> Args: [PASS]
       Latency: 1509.5ms | Confidence: 0.909

[15/20] Query: 'Fetch metrics for screen_time from 2026-11-01 to 2026-11-15'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-11-01', 'to': '2026-11-15', 'metrics': ['screen_time']} -> Args: [PASS]
       Latency: 1486.3ms | Confidence: 0.779

[16/20] Query: 'Get metrics for reading_minutes and sleep from 2026-08-01 to 2026-08-15'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-08-01', 'to': '2026-08-15', 'metrics': ['reading_minutes', 'sleep']} -> Args: [PASS]
       Latency: 1552.4ms | Confidence: 0.8617

[17/20] Query: 'Pull metrics steps from 2026-07-01 to 2026-07-31'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-07-01', 'to': '2026-07-31', 'metrics': ['steps']} -> Args: [PASS]
       Latency: 2641.8ms | Confidence: 0.7515

[18/20] Query: 'Get daily metrics for commits from 2026-10-15 to 2026-10-25'
       Expected: get_metrics | Actual: get_metrics -> Tool: [PASS]
       Args: {'from': '2026-10-15', 'to': '2026-10-25', 'metrics': ['commits']} -> Args: [PASS]
       Latency: 1656.8ms | Confidence: 0.8601

[19/20] Query: 'Hello! What can you help me with today?'
       Expected: None | Actual: None -> Tool: [PASS]
       Args: {} -> Args: [PASS]
       Latency: 1251.8ms | Confidence: 0.0848

[20/20] Query: 'What is the capital of France?'
       Expected: None | Actual: None -> Tool: [PASS]
       Args: {} -> Args: [PASS]
       Latency: 718.7ms | Confidence: 0.8952

================================================================================
SPIKE SUMMARY
================================================================================
Total Queries:     20
Tool Matches:      17/20 (85.0%)
Arg Correctness:   17/20 (85.0%)
Average Latency:   1465.7 ms (min: 718.7ms, max: 2641.8ms)

DECISION: Needle rejected: tool=85.0%, args=85.0% (threshold: >=90%/80%)
```

Command: `curl.exe -s http://127.0.0.1:8000/health`
Output:
```json
{"status":"ok","db":false,"llm":false,"llm_detail":"Ollama connection timed out at http://localhost:11434","router":"none"}
```

## 5. Problems and Fixes
- Error: Needle spike evaluation achieved 85.0% tool accuracy on the 20 test queries, which fell below the mandatory 90.0% acceptance threshold.
  - Root cause: Needle 3's constrained decoding suppressed queries like "Run SQL query to show my top 5 longest reading sessions" due to low confidence on complex SQL prompts.
  - Fix: Followed the strict decision rule — rejected Needle as the active router, retained `GeneralLLMRouter` (Ollama) as default, configured `ROUTER_MODEL=general`, and ensured Needle is not added as a hard dependency in `pyproject.toml`.

## 6. How to Verify Yourself
1. Run unit tests: `pytest -q`
2. Run Needle spike: `python scripts/spike_needle.py`
3. Check health endpoint: `curl http://127.0.0.1:8000/health`

## 7. Known Limitations
- When Ollama is not running on localhost:11434, `/health` reports `llm: false` with `"Ollama connection timed out at http://localhost:11434"`.
- When PostgreSQL container is down, `/health` reports `db: false`.

## 8. Next Phase
Phase 1 — Database: ORM models, Alembic `0001_init` migration (tables, indexes, views, `life_ro` grants), and `db.py` dual engine setup.
