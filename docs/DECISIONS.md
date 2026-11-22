# DECISIONS (date | decision | reason)

| Date | Decision | Reason |
|---|---|---|
| 2026-11-22 | Docker init SQL (`/docker-entrypoint-initdb.d/`) creates `vector` extension and `life_ro` role only; `GRANT SELECT ON views TO life_ro` lives in the Alembic migration (`0001_init`), not in init SQL | Views don't exist until migrations run; granting in init SQL would silently fail. ARCHITECTURE §4b and DATA_AND_RAG §2 imply this split; making it explicit. |
| 2026-11-22 | `SearchHit.note_id` is the parent note FK (`note_chunks.note_id`), not the chunk PK | DATA_AND_RAG §5 lists note_date/source_type/snippet but not which ID; API_SPEC uses `note_id`; using the parent note FK is most useful to callers wanting to fetch the full note. |
| 2026-11-22 | PII masking applies to outbound payload only when model is not `ollama/*`; log-level redaction is always-on regardless of model | SECURITY §2 and AGENT_WORKFLOW Part B both say cloud-only payload masking; SECURITY §5 says always redact in logs. No conflict — two separate code paths. Noted for implementor clarity. |
| 2026-11-22 | Life-API uses TWO model roles: (1) GENERAL model (Ollama, LLM_MODEL in .env) for Text-to-SQL, result summaries, daily insights, query rewriting, structured JSON; (2) ROUTER model (Needle, optional, ROUTER_MODEL in .env) ONLY for the ReAct agent's tool selection step | Needle is NOT a replacement for the general model because it is a tool-calling model with little general chat ability; it never writes SQL or prose. |
