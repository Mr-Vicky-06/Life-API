# API_SPEC — Endpoints and Schemas

Base: `http://localhost:8000`. Every `/v1/*` route requires header `X-API-Key: <APP_API_KEY>` (401 otherwise). All responses are JSON. Errors use one envelope.

## Error Envelope
```json
{ "error": { "code": "sql_rejected", "message": "Only SELECT statements are allowed.", "request_id": "uuid" } }
```
Codes: `unauthorized`(401), `validation_error`(422), `sql_rejected`(422), `sql_failed`(422), `guardrail_blocked`(400), `llm_unavailable`(503), `llm_bad_output`(502), `internal`(500). Never leak stack traces or secrets.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | no auth; `{"status":"ok","db":true,"llm":true|false}` |
| POST | `/v1/ingest/github` | pull commits (body `{"days":30}`) |
| POST | `/v1/ingest/{health\|reading\|screen_time}` | multipart CSV upload, field `file` |
| POST | `/v1/ingest/notes` | JSON list of notes |
| GET | `/v1/metrics` | query: `from`, `to`, `metrics` (comma list) |
| POST | `/v1/query` | natural-language question → Text-to-SQL answer (uses `REFERENCE_DATE` or today; `"last N days"` = `date > ref - N`; small results `< 5` cells or `1x<=3` use deterministic template; larger results verify every cited number appears in returned rows) |
| POST | `/v1/search` | hybrid search over notes |
| POST | `/v1/agent/chat` | ReAct agent |
| GET | `/v1/insights/daily` | structured daily summary (LLM, cached per date) |

## Pydantic Schemas (put in `app/schemas/`)
```python
class IngestResult(BaseModel):
    source: str; inserted: int; updated: int; skipped: int; errors: list[str] = []

class MetricsResponse(BaseModel):
    from_date: date; to_date: date
    rows: list[dict[str, float | int | str | None]]   # one per day, only requested metrics

class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: list[str] = Field(default_factory=list, max_length=4)

class QueryResponse(BaseModel):
    question: str; standalone_question: str
    sql: str; explanation: str
    columns: list[str]; rows: list[list[Any]]; row_count: int
    summary: str; model: str; latency_ms: int

class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    top_k: int = Field(default=8, ge=1, le=20)
    source_type: Literal["journal","reading_note","commit_message"] | None = None
    date_from: date | None = None; date_to: date | None = None

class SearchHit(BaseModel):
    note_id: int; note_date: date; source_type: str; snippet: str; score: float

class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    session_id: str | None = None

class AgentStep(BaseModel):
    thought: str; action: Literal["sql_query","search_notes","get_metrics","final"]
    action_input: dict; observation: str | None = None

class AgentResponse(BaseModel):
    answer: str; steps: list[AgentStep]; model: str

class DailyInsight(BaseModel):
    timestamp: date
    summary: str = Field(max_length=300)
    metrics: dict[str, float | int]      # sleep_hours, github_commits, reading_minutes, steps, screen_minutes
    insights: str = Field(max_length=400)
```
Sample `/v1/insights/daily` response:
```json
{ "timestamp": "2026-11-02", "summary": "High productivity day aligned with 8.2 hours of sleep.",
  "metrics": {"sleep_hours": 8.2, "github_commits": 14, "reading_minutes": 45},
  "insights": "Commit frequency peaked after a high-sleep night." }
```
`metrics` numbers MUST come from the database, not the LLM; the LLM only writes `summary` and `insights`.

## Structured Output Contract (`gateway/structured.py`)
`call_structured(model_cls, messages) -> model_cls`:
1. Request JSON (`response_format={"type":"json_object"}`; for Ollama pass `format="json"`), include the model's JSON schema in the system prompt.
2. Parse: strip code fences → `json.loads`. If it fails, run `repair_json` (close unbalanced brackets/quotes, remove trailing commas).
3. `model_cls.model_validate(data)`.
4. On failure: ONE retry appending the validation error to the prompt. Still failing → raise `LLMBadOutput` (HTTP 502). Never return unvalidated model output.
