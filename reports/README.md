# Phase Reports Index

| Phase | Name | Status | Gate Result | Date | Commit Hash |
|---|---|---|---|---|---|
| 0 | Scaffold | Passed | `curl /health` 200 OK + `pytest -q` 2 passed | 2026-11-22 | cd50d18 |
| Add-on | LLM Setup & Needle | Passed | Live LLM call OK (cold 3.4s, warm 266ms); /health llm=true | 2026-11-23 | dbef3ee |
| 1 | Database | Passed | Alembic upgrade/downgrade OK; 5 db tests passed; /health db=true, llm=true | 2026-11-23 | 5872c00 |
| 2 | Ingestion + Seed | Passed | Seed idempotent (90/340/60/270/53/53); 15 unit/ingest tests passed; full suite 30 passed | 2026-11-23 | 5728ae1 |
| 3 | Model Gateway + PII | Passed | PII masking & respx wire test OK (0 emails/tokens); 20 security tests passed; live structured Ollama test passed; full suite 51 passed | 2026-11-23 | 0a4b335 |
| 4 | Embeddings + Hybrid Search | Passed | Hybrid search RRF (k=60) & Query Rewrite OK; live search checks passed; 74 tests passed | 2026-11-24 | phase-4-search |
| 5 | Text-to-SQL | Passed | Step 0A/0B/0C fixed; 75 security/golden/query tests passed; full suite 135 passed; live `/v1/query` OK; bench 6/10 | 2026-11-25 | phase-5-text-to-sql |
| 5.1 | SQL Accuracy & Safer Summaries | Passed | Default switched to `ollama/qwen2.5-coder:7b`; bench `21/22` (`9/10` golden, `12/12` heldout, `9/9` untuned, `4.3s` mean); 88 gate, 153 suite, 3 live passed | 2026-11-25 | phase-5-1-complete |
| 6 | Metrics + Insights API | Passed | `/v1/metrics` & `/v1/insights/daily` RO+cached+verified; 11 integration, 4 live (`14.3s` insight), 164 full suite passed; live curls OK | 2026-11-25 | phase-6-complete |
| 7 | ReAct Agent | Passed | Step 0A/0B fixed; ReAct 3 tools, 5-step cap, 100-session LRU, <data> isolation; 15 agent gate, 5 live, 180 full suite passed; bench 14/15; 2-turn curl OK | 2026-11-25 | phase-7-complete |
| 8 | Dashboard | Passed | `/v1/screen-time` curl + 6 metrics + 11 dashboard unit/AppTest + 193 full suite passed; Playwright 5-view visual check (0 console errors) | 2026-11-25 | phase-8-complete |
| 8.1 | Real Data Showcase (Corrected) | Superseded / Opt-in | Moved composite public demo behind `--composite-demo`; restored default `scripts.seed --reset`, nullable unmeasured columns (`0002_nullable_reading_minutes`), `DATA_LABEL`, verbatim license audit & Zenodo CC-BY 4.0 attribution | 2026-11-26 | phase-9-hardening |
| 9 | Hardening | Passed | 22/22 SQL bench, 15/15 agent bench, Security & PRD matrices verified, `ruff check .` clean, 202 non-live + 5 live passed, fresh-clone on `DB_PORT=5433` passed | 2026-11-27 | phase-9-complete / v0.1.0 |
