# Selected Agent Skills for Life-API

This document catalogs the skills selected from `vignesh-universal-skill-book` to assist across the 10 build phases of Life-API. Per the golden rules in `ANTIGRAVITY.md`, `ANTIGRAVITY.md` and repository specification documents (`docs/`) strictly take precedence if any skill suggests conflicting dependencies, frameworks, or security patterns.

---

## 1. Selected Skills (Copied to `.agent/skills/`)

| Skill | Why it is needed | Phase(s) where it applies |
|---|---|---|
| `fastapi-pro` | Best-practice async router architecture, SQLAlchemy 2.0 session lifecycle, and Pydantic v2 schemas adhering to zero-leak error boundaries. | Phase 0, Phase 6, Phase 7 |
| `postgresql` | Schema design patterns, index strategies (HNSW vector cosine indexing, GIN FTS index), and view/role isolation for PostgreSQL 16 + pgvector. | Phase 1, Phase 2 |
| `rag-engineer` | Chunking strategies (sentence-boundary splitting, metadata headers), pgvector cosine embedding generation, and hybrid search RRF fusion. | Phase 4 |
| `sql-injection-testing` | Comprehensive testing of Text-to-SQL validators, AST parsing validation with `sqlglot`, read-only enforcement, and preventing SQL injection vectors. | Phase 5, Phase 9 |
| `python-testing-patterns` | Clean pytest fixture architecture, TestClient integration, respx HTTP mocking, and deterministic golden test harnesses. | Phase 0, Phase 2, Phase 3, Phase 5, Phase 7, Phase 9 |
| `api-security-best-practices` | OWASP API security compliance, constant-time API key auth (`X-API-Key`), rate limiting middleware, and PII masking / secret redaction. | Phase 0, Phase 3, Phase 9 |
| `kpi-dashboard-design` | Streamlit executive layout hierarchy, metric cards, Plotly scatter/trendline visualization, and user experience patterns. | Phase 8 |
| `git-advanced-workflows` | Clean branch-per-phase git hygiene, conventional commit formatting, `--no-ff` merges, tagging, and phase progress tracking. | All Phases (0–9) |

---

## 2. Sample Rejected Skills and Reasons

The following skills from the universal book were reviewed and rejected to keep the project focused, lightweight, and compliant with the pinned stack:

| Rejected Skill | Reason for Rejection |
|---|---|
| `crewai` / `langchain` / `llamaindex` | Conflicted with `ANTIGRAVITY.md` Golden Rule 3 & `ARCHITECTURE.md` Section 5: ReAct agent must be hand-written with no external agent frameworks. |
| `prisma` / `drizzle` / `typeorm` | Node/TypeScript ORMs not applicable to our pinned Python 3.11+ + SQLAlchemy 2.0 stack. |
| `pinecone` / `weaviate` / `qdrant` | Conflicted with pinned stack: vector storage is exclusively PostgreSQL 16 + pgvector. |
| `react` / `nextjs` / `vue` | Frontend framework skills not applicable; dashboard is strictly Streamlit + Plotly. |
| `kubernetes` / `helm` / `terraform` | Out of scope per `PRD.md` Section 5: no deployment automation or cloud infrastructure orchestration. |
| `stripe-integration` / `payment-integration` | Out of scope per `PRD.md` Section 5: personal owner-only API, no payments or billing. |
| `oauth-integration` | Out of scope per `PRD.md` Section 5: health/sleep data imported via CSV/JSON exports, no OAuth flows. |
| `threejs-skills` / `algorithmic-art` | 3D visual and canvas rendering skills unrelated to life telemetry dashboard. |
| `azure-cosmos-db-py` / `aws-dynamodb` | Cloud proprietary NoSQL databases unrelated to local PostgreSQL architecture. |
| `playwright-skill` | E2E browser automation skill; API and dashboard verified via pytest TestClient and manual checklist per `TESTING.md`. |
| `temporal-python-testing` | Temporal distributed workflow orchestrator not part of the pinned stack. |
