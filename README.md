# Document Intelligence Platform

## Setup (3 commands)

```bash
pip install -r requirements.txt
cp .env.example .env          # Add your GROQ_API_KEY
uvicorn app.main:app --reload
```

## Run tests

```bash
pytest
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /validate | Validate envelope — returns enriched envelope |
| POST | /match | LLM commodity matching — returns enriched envelope |
| POST | /process | Full pipeline — validate + match |

## LLM swap point

The LLM integration is isolated in `app/services/matching.py` in the `_call_llm()` function.
Set `USE_MOCK_LLM=true` in your `.env` to use the deterministic mock without an API key.

## Design decisions

- **Threshold from envelope**: `confidence_threshold` is always read from
  `processing_instructions` in the envelope. It is never hardcoded in service code.
- **Append-only audit**: Every service appends its entry to `envelope.audit`.
  No stage ever removes or replaces prior entries.
- **Graceful LLM failure**: LLM exceptions are caught at the service layer.
  A timeout or API error results in `source: "no_match"`, `route: "hitl_review"`,
  and a logged audit entry. The pipeline always returns HTTP 200.
- **Business failures ≠ HTTP errors**: Low confidence, bad dates, and missing
  commodity codes are business outcomes, not HTTP errors. They return HTTP 200
  with a populated `decision` and `validation_results`. Only malformed JSON
  input returns HTTP 422.

## What I would add next

- Persistent audit trail (PostgreSQL with asyncpg)
- Multi-tenant configuration store (thresholds and rules per tenant_id)
- Async task queue for batch processing (Celery + Redis)
- OpenTelemetry traces with envelope_id as the span attribute
- Rate limiting per tenant_id
