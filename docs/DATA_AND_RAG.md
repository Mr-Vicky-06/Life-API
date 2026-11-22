# DATA_AND_RAG — Schema, Ingestion, Retrieval, Text-to-SQL

## 1. Tables (Alembic migration `0001_init`)
All timestamps `timestamptz` (UTC). `date` columns are owner-local dates.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE health_daily (
  date date PRIMARY KEY,
  sleep_hours numeric(4,2), sleep_score int, deep_sleep_min int,
  hrv_ms numeric(6,2), resting_hr int, steps int, source text NOT NULL DEFAULT 'csv'
);
CREATE TABLE github_commits (
  sha text PRIMARY KEY, repo text NOT NULL, committed_at timestamptz NOT NULL,
  commit_date date NOT NULL, message text, additions int DEFAULT 0, deletions int DEFAULT 0
);
CREATE TABLE reading_log (
  id bigserial PRIMARY KEY, date date NOT NULL, title text NOT NULL,
  pages_read int DEFAULT 0, minutes int DEFAULT 0,
  UNIQUE (date, title)
);
CREATE TABLE screen_time (
  date date NOT NULL, category text NOT NULL, minutes int NOT NULL,
  PRIMARY KEY (date, category)
);
CREATE TABLE notes (
  id bigserial PRIMARY KEY, ts timestamptz NOT NULL, note_date date NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('journal','reading_note','commit_message')),
  content text NOT NULL, content_hash text NOT NULL UNIQUE
);
CREATE TABLE note_chunks (
  id bigserial PRIMARY KEY, note_id bigint NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  chunk_idx int NOT NULL, content text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',
  embedding vector(384) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  UNIQUE (note_id, chunk_idx)
);
CREATE INDEX note_chunks_tsv_idx ON note_chunks USING gin (tsv);
CREATE INDEX note_chunks_emb_idx ON note_chunks USING hnsw (embedding vector_cosine_ops);
CREATE TABLE query_log (
  id bigserial PRIMARY KEY, ts timestamptz DEFAULT now(), endpoint text,
  question_masked text, sql text, latency_ms int, model text, ok boolean, error text
);
```

## 2. Allowlisted Views (the ONLY objects Text-to-SQL may touch)
```sql
CREATE VIEW v_daily_summary AS
SELECT h.date, h.sleep_hours, h.sleep_score, h.deep_sleep_min, h.hrv_ms, h.resting_hr, h.steps,
       COALESCE(c.commits,0) AS commits, COALESCE(c.lines_added,0) AS lines_added,
       COALESCE(r.pages_read,0) AS pages_read, COALESCE(r.reading_minutes,0) AS reading_minutes,
       COALESCE(s.screen_minutes,0) AS screen_minutes
FROM health_daily h
LEFT JOIN (SELECT commit_date AS date, count(*) commits, sum(additions) lines_added
           FROM github_commits GROUP BY 1) c USING (date)
LEFT JOIN (SELECT date, sum(pages_read) pages_read, sum(minutes) reading_minutes
           FROM reading_log GROUP BY 1) r USING (date)
LEFT JOIN (SELECT date, sum(minutes) screen_minutes FROM screen_time GROUP BY 1) s USING (date);

CREATE VIEW v_commits AS SELECT sha, repo, committed_at, commit_date, additions, deletions FROM github_commits;
CREATE VIEW v_screen_time AS SELECT date, category, minutes FROM screen_time;
CREATE VIEW v_reading AS SELECT date, title, pages_read, minutes FROM reading_log;
```
Grant: `GRANT SELECT ON v_daily_summary, v_commits, v_screen_time, v_reading TO life_ro;` Nothing else. `commit_message` text is intentionally NOT exposed to SQL (it goes through notes/RAG).

## 3. Ingestion Pipeline
Order: `fetch → parse → clean → validate (Pydantic) → upsert → (notes only) chunk → embed → insert`.

| Source | Input | Method |
|---|---|---|
| GitHub | `GITHUB_TOKEN`, `GITHUB_USERNAME` | `GET https://api.github.com/users/{u}/events` then `GET /repos/{owner}/{repo}/commits?author={u}&since=...` via httpx, paginated, 30-day default window; on missing token, skip with a warning |
| Health | CSV columns: `date,sleep_hours,sleep_score,deep_sleep_min,hrv_ms,resting_hr,steps` | `POST /v1/ingest/health` (multipart) |
| Reading | CSV `date,title,pages_read,minutes` | `POST /v1/ingest/reading` |
| Screen time | CSV `date,category,minutes` | `POST /v1/ingest/screen_time` |
| Notes | JSON `[{ts, source_type, content}]` | `POST /v1/ingest/notes` |

**Cleaning rules (`cleaning.py`)**: strip HTML tags, collapse Markdown syntax (`#`, `*`, backticks, links → text), collapse whitespace, drop empty rows, dedupe by natural key (upsert `ON CONFLICT DO UPDATE`), notes dedupe by SHA-256 `content_hash`. Parse timestamps with timezone → convert to UTC; naive timestamps assumed `APP_TIMEZONE`.

**Idempotency**: re-running any ingest with the same input must not create duplicates (tested).

**Seed (`scripts/seed.py`)**: `random.seed(42)`, 90 days ending today. Make sleep weakly correlated with commits (commits ≈ 2 + 3·(sleep−6.5)+noise, min 0) so the dashboard correlation is meaningful. Insert ≥ 40 journal notes and ≥ 20 reading notes with realistic sentences, then chunk and embed them.

## 4. Chunking & Embedding
- Chunk size 500 chars, overlap 80, split on sentence boundaries when possible.
- Each chunk text stored as: `[{note_date} | {source_type}] {text}` (metadata header included in embedding and FTS).
- Model loaded once at startup (lazy singleton). Batch size 32. Normalize embeddings.

## 5. Hybrid Search (`rag/hybrid.py`)
1. Embed query → vector leg: `ORDER BY embedding <=> :q LIMIT 20`.
2. Term leg: `plainto_tsquery('english', :q)`, rank `ts_rank_cd(tsv, query)`, `LIMIT 20`.
3. Fuse with RRF: `score(d) = Σ 1/(60 + rank_leg(d))`. Return top 8 with `score`, `note_date`, `source_type`, `snippet`.
4. Optional filters: `date_from`, `date_to`, `source_type`.

## 6. Query Rewriting (`rag/rewrite.py`)
Input: last ≤4 turns + new question. If the question has no self-contained meaning (pronouns, "how about last week"), call the gateway with a rewrite prompt and return a standalone question. Output schema: `{"standalone_question": str}`. Skip the LLM call if the question already has ≥6 words and no anaphora keywords (`it, that, those, then, how about, what about`).

## 7. Text-to-SQL (`sql_agent/`)
Pipeline:
1. `schema_prompt.py` builds the prompt from the 4 allowlisted views (column names, types, one-line meanings) plus 5 few-shot examples and today's date in `APP_TIMEZONE`.
2. `generator.py` asks the gateway for JSON `{"sql": str, "explanation": str}` (structured output).
3. `validator.py` (see `SECURITY.md`): parse with sqlglot (dialect `postgres`), exactly one statement, `SELECT` only, tables ⊆ allowlist, no blocked functions, enforce `LIMIT ≤ 200` (add if missing).
4. `executor.py` runs it with `DATABASE_URL_RO`, `SET LOCAL statement_timeout = '5s'`, read-only transaction.
5. On SQL error: ONE repair attempt (send error text back to the model). Then fail with HTTP 422 `sql_failed`.
6. Gateway summarizes rows into 1–3 sentences (rows capped to 50 in the prompt).

Few-shot examples to embed (use exactly these patterns):
- avg sleep on commit days → `SELECT round(avg(sleep_hours),2) AS avg_sleep FROM v_daily_summary WHERE commits > 0;`
- last 7 days steps → `SELECT date, steps FROM v_daily_summary WHERE date >= current_date - 7 ORDER BY date;`
- correlation → `SELECT round(corr(sleep_hours, commits)::numeric,3) AS r FROM v_daily_summary;`
- weekly commits → `SELECT date_trunc('week', date)::date AS week, sum(commits) AS commits FROM v_daily_summary GROUP BY 1 ORDER BY 1;`
- top screen category → `SELECT category, sum(minutes) AS total FROM v_screen_time GROUP BY 1 ORDER BY 2 DESC LIMIT 5;`
