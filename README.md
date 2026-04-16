# Document Intelligence Platform — Full Documentation

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [Why This System Exists](#why-this-system-exists)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [The JSON Execution Envelope](#the-json-execution-envelope)
6. [Pipeline Flow](#pipeline-flow)
7. [File-by-File Reference](#file-by-file-reference)
8. [API Endpoints](#api-endpoints)
9. [Testing](#testing)
10. [Design Principles](#design-principles)
11. [Setup & Running](#setup--running)

---

## What This System Does

This is a **FastAPI microservice** that acts as a downstream processing layer for a document extraction platform. The upstream system (OCR / ML pipeline) extracts data from shipping documents (PDFs, manifests, invoices) and produces a structured **JSON Execution Envelope** containing the extracted fields along with confidence scores.

This service receives that envelope and performs three jobs:

1. **Validates** the extracted data — checks that required fields exist, that confidence scores meet thresholds, that dates are reasonable.
2. **Matches** commodity descriptions to HS (Harmonized System) codes using an LLM — only when the extracted commodity code has low confidence.
3. **Routes** the document to one of three outcomes: `auto_approve`, `hitl_review` (human-in-the-loop), or `rejected`.

Everything is **configuration-driven from the envelope itself** — thresholds, routing rules, and workflow names come from the incoming data, not from hardcoded service config.

---

## Why This System Exists

In logistics and customs processing, shipping documents arrive in high volume. An upstream OCR/ML system extracts fields like shipment IDs, dates, commodity codes, and recipient names — but extraction is never perfect. Each field comes with a confidence score (0.0–1.0).

The problems this service solves:

- **When can we trust the extraction?** Low-confidence fields need flagging.
- **What if the commodity code is wrong?** The LLM can cross-check the commodity description against a reference catalog and suggest a better HS code.
- **Who reviews problems?** Depending on the client's configuration, failed documents either go to a human reviewer or get rejected outright.
- **Audit trail**: Every decision must be traceable. The envelope accumulates audit entries from each processing stage, so you can see exactly what happened and why.

---

## Architecture

```
                         ┌─────────────┐
                         │  Upstream    │
                         │  OCR/ML     │
                         │  Pipeline   │
                         └──────┬──────┘
                                │ JSON Execution Envelope
                                ▼
                    ┌───────────────────────┐
                    │   FastAPI Routers     │
                    │  /validate /match     │
                    │  /process  /health    │
                    └───────────┬───────────┘
                                │
                  ┌─────────────┼─────────────┐
                  ▼             ▼             ▼
          ┌──────────┐  ┌──────────┐  ┌──────────┐
          │Validation│  │ Matching │  │ Logging  │
          │ Service  │  │ Service  │  │ + Audit  │
          └────┬─────┘  └────┬─────┘  └──────────┘
               │              │
               │         ┌────┴────┐
               │         ▼         ▼
               │    ┌─────────┐ ┌───────┐
               │    │  Groq   │ │ Mock  │
               │    │  API    │ │ LLM   │
               │    └─────────┘ └───────┘
               │
               ▼
     Enriched Envelope (validation_results,
       matching_results, decision, audit)
```

### Layer Separation

| Layer | Files | Responsibility |
|-------|-------|----------------|
| **Routers** | `app/routers/*.py` | HTTP concerns only — receive request, call service, return response |
| **Services** | `app/services/*.py` | Pure business logic — validation rules, LLM calls. No HTTP imports. |
| **Models** | `app/models/*.py` | Data contracts — Pydantic v2 schemas for envelope, responses |
| **Config** | `app/config.py` | Service identity constants only (name, version). No business logic. |
| **Tests** | `tests/*.py` | Mock all external calls, test business rules in isolation |

---

## Project Structure

```
document_intelligence/
├── app/
│   ├── __init__.py              # Empty — marks directory as Python package
│   ├── main.py                  # FastAPI app factory, 422 handler, logging, router registration
│   ├── config.py                # SERVICE_NAME and VERSION constants
│   ├── models/
│   │   ├── __init__.py          # Empty
│   │   ├── envelope.py          # All Pydantic v2 envelope models (10 models)
│   │   └── responses.py         # HTTP error response models (3 models)
│   ├── services/
│   │   ├── __init__.py          # Empty
│   │   ├── validation.py        # Validation logic — schema, confidence, date, routing, audit
│   │   └── matching.py          # LLM matching + in-memory commodity catalog
│   └── routers/
│       ├── __init__.py          # Empty
│       ├── health.py            # GET /health
│       ├── validate.py          # POST /validate
│       ├── match.py             # POST /match
│       └── process.py           # POST /process (full pipeline)
├── tests/
│   ├── __init__.py              # Empty
│   ├── conftest.py              # Shared fixtures and LLM mocks
│   ├── test_validate.py         # 3 validation tests
│   ├── test_match.py            # 2 matching tests
│   └── test_process.py          # 3 pipeline tests
├── requirements.txt             # All dependencies with version pins
├── .env.example                 # Environment variable template
└── README.md                    # This file
```

---

## The JSON Execution Envelope

The envelope is the **single data contract** that flows through the entire system. Every endpoint receives it and returns it. The service **never removes or overwrites upstream fields** — it only appends new sections.

### Input Envelope (what arrives)

```
envelope_id              → Unique identifier for this processing run
schema_version           → Envelope format version (e.g., "envelope-v1")
tenant                   → Who this document belongs to (id + name)
document                 → What document was processed (type, filename, pages)
extraction               → All extracted fields, each with value + confidence
processing_instructions  → Client-specific config: threshold, workflow, hitl flag
validation_results       → null (to be filled by this service)
matching_results         → null (to be filled by this service)
decision                 → null (to be filled by this service)
audit                    → [] (entries appended by each processing stage)
```

### Output Envelope (what's returned)

Same as input, but with four new sections populated:

- **validation_results** — passed/failed, list of failed fields, reasons for each failure
- **matching_results** — matched HS code, confidence, rationale, source (catalog/llm/no_match)
- **decision** — routing decision: auto_approve, hitl_review, or rejected
- **audit** — chronological trail of everything that happened, with timestamps

---

## Pipeline Flow

The main pipeline (`POST /process`) executes in this exact order:

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│   Ingest    │────▶│   Validate   │────▶│    Match     │────▶│  Deliver   │
│  (receive   │     │  (always)    │     │  (conditional│     │ (return    │
│   envelope) │     │              │     │   — only if  │     │  enriched  │
│             │     │              │     │   commodity  │     │  envelope) │
│             │     │              │     │   confidence │     │            │
│             │     │              │     │   < threshold│     │            │
└─────────────┘     └──────────────┘     └──────────────┘     └────────────┘
```

### Stage 1: Validation (always runs)

Three checks are performed, in order:

**1a. Schema completeness check**
- `shipment_id.value` must exist and be non-empty
- `recipient_name.value` must exist and be non-empty
- At least one of `commodity_code` or `commodity_desc` must be present

**1b. Confidence threshold check**
- Every field in `extraction` is checked against `processing_instructions.confidence_threshold`
- The threshold comes from the envelope — never hardcoded
- Fields with confidence below threshold are collected with a reason string

**1c. Date validation**
- `ship_date.value` is parsed as ISO 8601 (YYYY-MM-DD)
- Must not be in the future
- Must not be older than 365 days from today

**1d. Decision routing** — based on collected failures:
- No failures → `auto_approve`
- Failures + `hitl_on_failure=true` → `hitl_review`
- Failures + `hitl_on_failure=false` → `rejected`

**1e. Audit** — an AuditEntry is appended to `envelope.audit` with timestamp, service name, result, and details.

### Stage 2: Matching (conditional)

Only runs if `commodity_code` is missing or its confidence is below the threshold.

**2a. Commodity description resolution**
- Uses `commodity_desc.value` if available, otherwise falls back to `commodity_code.value`

**2b. LLM call via Groq API**
- Sends the commodity description + full reference catalog to `llama-3.3-70b-versatile`
- LLM returns a JSON object with: matched_code, match_confidence, rationale, source
- 10-second timeout on the HTTP call

**2c. Graceful degradation**
- If the LLM call fails (timeout, HTTP error, bad JSON, any exception):
  - Sets `matching_results` to no_match
  - Overrides `decision.route` to `hitl_review`
  - Logs an audit entry with `result="error"`
  - Returns normally — **never crashes the pipeline**

**2d. Post-match override**
- Even on success, if the match confidence is below 0.70, overrides route to `hitl_review`
- This catches cases where the LLM found a match but isn't confident enough

**2e. Audit** — an AuditEntry is appended with match details.

### Stage 3: Deliver

The enriched envelope is returned as the HTTP response body. No fields from the original input are modified or removed.

---

## File-by-File Reference

### `app/config.py`

Two constants: `SERVICE_NAME = "document-intelligence"` and `VERSION = "1.0.0"`. These are used by the `/health` endpoint and the FastAPI app metadata. Nothing else goes here — no thresholds, no business rules.

---

### `app/models/envelope.py` — 10 Pydantic Models

| Model | Purpose |
|-------|---------|
| `ExtractedField` | A single OCR/ML result: `value` (string) + `confidence` (float 0.0–1.0). This is the atomic unit of extraction data. |
| `Extraction` | All extracted fields from the document. `shipment_id`, `ship_date`, and `recipient_name` are required. `commodity_code` and `commodity_desc` are optional. |
| `ProcessingInstructions` | Client-driven configuration embedded in every envelope. Contains `workflow` (string identifier), `confidence_threshold` (float 0.0–1.0), and `hitl_on_failure` (bool). This is how the service knows what rules to apply. |
| `TenantInfo` | Identifies the client: `id` and `name`. Enables future multi-tenant features. |
| `DocumentInfo` | Metadata about the source document: `type` (e.g., "shipping_manifest"), `filename`, `page_count`. |
| `ValidationResult` | Output of the validation stage: `passed` (bool), `failed_fields` (list), `reasons` (field→reason mapping). |
| `MatchResult` | Output of the matching stage: `matched_code`, `match_confidence`, `rationale`, `fallback_used`, `source` (one of: catalog_exact, llm_match, no_match). |
| `Decision` | The routing decision: `route` (one of: auto_approve, hitl_review, rejected). |
| `AuditEntry` | A single audit trail entry: `timestamp` (UTC), `service`, `action`, `envelope_id`, `result`, `details` (dict). |
| `Envelope` | The top-level container. Holds all of the above. `validation_results`, `matching_results`, `decision` start as None and get populated during processing. `audit` starts as an empty list. |

---

### `app/models/responses.py` — 3 Models

| Model | Purpose |
|-------|---------|
| `FieldError` | Used in 422 error responses: `field` name + `reason` string. |
| `ValidationErrorResponse` | The structured body returned for HTTP 422 errors. Has `error` (always "validation_failed"), `message`, and `failed_fields` list. This replaces FastAPI's default validation error format with our own. |
| `HealthResponse` | The body returned by `GET /health`: `status`, `service`, `version`. |

---

### `app/services/validation.py` — `run_validation(envelope) → envelope`

Pure business logic — no FastAPI imports, no HTTP concerns, no I/O.

**Function: `run_validation(envelope: Envelope) -> Envelope`**

Takes an envelope, runs all checks, returns the enriched envelope. Never raises exceptions for business rule failures — failures are captured in `validation_results` and the envelope is returned normally.

**Internal flow:**

1. Reads `confidence_threshold` from `envelope.processing_instructions`
2. Checks schema completeness (lines 37–68):
   - `shipment_id.value` must be non-empty
   - `recipient_name.value` must be non-empty
   - At least one commodity field must exist
3. Checks confidence for each field against threshold (lines 70–84):
   - Iterates over `shipment_id`, `ship_date`, `recipient_name`, `commodity_code`, `commodity_desc`
   - Skips None fields (optional ones may be absent)
4. Validates `ship_date` (lines 86–124):
   - Parses as YYYY-MM-DD
   - Rejects future dates
   - Rejects dates older than 365 days
5. Routes decision (lines 126–132):
   - No failures → `auto_approve`
   - Failures + `hitl_on_failure=true` → `hitl_review`
   - Failures + `hitl_on_failure=false` → `rejected`
6. Sets `envelope.validation_results` and `envelope.decision`
7. Appends an `AuditEntry` to `envelope.audit`
8. Returns the envelope

**Why this design:** Pure functions with no HTTP dependencies mean this logic is testable in isolation. The test suite calls `run_validation` through the HTTP endpoint, but the function itself knows nothing about HTTP.

---

### `app/services/matching.py` — `run_matching(envelope) → envelope`

Contains the LLM integration, in-memory catalog, mock, and graceful error handling.

**Module-level data:**

- `COMMODITY_CATALOG` — A list of 10 dicts, each with `hs_code`, `description`, `category`, `restricted`, `typical_weight_kg`. This is the reference catalog sent to the LLM for matching.

**Internal functions:**

| Function | Purpose |
|----------|---------|
| `_call_groq(commodity_desc) -> str` | Calls the Groq API (`llama-3.3-70b-versatile`) with the commodity description and full catalog as a prompt. Returns the raw LLM text response. Uses `httpx.AsyncClient` with a 10-second timeout. Reads `GROQ_API_KEY` from environment. |
| `_mock_llm_response(commodity_desc) -> str` | Deterministic mock for testing. Returns a hardcoded JSON match for descriptions containing "data processing", "laptop", or "notebook" → HS code `8471.30.0100`. Returns no_match for everything else. |
| `_call_llm(commodity_desc) -> str` | The swap point. Checks `USE_MOCK_LLM` env var. If true, calls the mock. Otherwise calls Groq. To switch providers, only this routing function and `_call_groq` need to change. |
| `run_matching(envelope) -> Envelope` | The public entry point. Resolves the commodity description, calls the LLM, parses the response, populates `matching_results`, applies the 0.70 confidence override, appends an audit entry. On any exception: sets no_match, routes to hitl_review, logs the error. Never re-raises. |

**Why the try/except catches `Exception`:** LLM calls can fail in many ways — network timeout, HTTP 500, rate limiting, malformed JSON response. The service must never crash a pipeline run because the LLM was unavailable. Instead, it degrades gracefully: the document goes to human review, and the error is recorded in the audit trail.

---

### `app/routers/health.py` — `GET /health`

Returns a `HealthResponse` with `status="ok"`, the service name, and version. Used by load balancers and monitoring to check if the service is alive.

---

### `app/routers/validate.py` — `POST /validate`

Receives an `Envelope`, calls `run_validation()`, returns the enriched envelope. Business rule failures (low confidence, bad dates) return HTTP 200 with the populated `validation_results` and `decision`. Only structurally invalid JSON (wrong types, missing required fields) triggers HTTP 422 via FastAPI's automatic validation.

---

### `app/routers/match.py` — `POST /match`

Receives an `Envelope`, checks if matching is needed (`commodity_code` is None or confidence < threshold). If needed, calls `run_matching()`. If not needed, returns the envelope unchanged. This avoids wasting an LLM call on documents that already have high-confidence commodity codes.

---

### `app/routers/process.py` — `POST /process`

The full pipeline orchestrator. Calls `run_validation()` unconditionally, then conditionally calls `run_matching()` if the commodity code needs verification. Returns the fully enriched envelope with audit entries from all executed stages.

---

### `app/main.py` — App Factory

Creates the FastAPI application and wires everything together:

1. **Logging configuration** — Sets up structured logging with `envelope_id` in every log line. Uses a custom `logging.Filter` (`_EnvelopeIdFilter`) that injects `envelope_id="N/A"` as a default when no envelope context is available, so the format string never fails.

2. **Custom 422 exception handler** — Replaces FastAPI's default validation error format with our `ValidationErrorResponse`. When the incoming JSON is malformed (missing fields, wrong types), the response body looks like:
   ```json
   {
     "error": "validation_failed",
     "message": "Request body failed schema validation",
     "failed_fields": [
       {"field": "body → extraction → shipment_id", "reason": "Field required"}
     ]
   }
   ```

3. **Router registration** — Includes all four routers: health, validate, match, process.

---

### `tests/conftest.py` — Test Fixtures

| Fixture | Purpose |
|---------|---------|
| `base_envelope_dict` | A valid envelope where all fields have confidence above 0.80 threshold. Used for happy-path tests. |
| `low_confidence_envelope_dict` | Derives from base, but sets `recipient_name` confidence to 0.71 and `commodity_code` to 0.58. Used for failure/degradation tests. |
| `missing_shipment_id_dict` | Derives from base, but deletes `shipment_id`. Used to test HTTP 422 for malformed input. |
| `mock_llm_success` | Patches `_call_llm` to return a deterministic successful match (HS code 8471.30.0100, confidence 0.91). No real API call happens. |
| `mock_llm_timeout` | Patches `_call_llm` to raise `httpx.TimeoutException`. Tests that the service degrades gracefully. |
| `client` | A `TestClient` wrapping the FastAPI app. Used to make HTTP requests in tests without starting a real server. |

---

### `tests/test_validate.py` — 3 Tests

| Test | What it verifies |
|------|------------------|
| `test_validate_happy_path_auto_approve` | All fields above threshold → `passed=True`, route=`auto_approve`, empty failed_fields, 1 audit entry |
| `test_validate_low_confidence_hitl_review` | Two fields below threshold → `passed=False`, route=`hitl_review`, both fields in failed_fields |
| `test_validate_hitl_on_failure_false_rejected` | Same low-confidence envelope but `hitl_on_failure=false` → route=`rejected` |

---

### `tests/test_match.py` — 2 Tests

| Test | What it verifies |
|------|------------------|
| `test_match_successful_llm_match` | Low confidence commodity triggers matching → mock returns match → `matching_results` populated with correct HS code |
| `test_match_llm_timeout_graceful_degradation` | LLM times out → HTTP 200 (not 500), route=`hitl_review`, source=`no_match`, audit has error entry |

---

### `tests/test_process.py` — 3 Tests

| Test | What it verifies |
|------|------------------|
| `test_process_full_pipeline_happy_path` | All fields pass → auto_approve, no matching triggered, 1 audit entry (validation only) |
| `test_process_full_pipeline_triggers_matching` | Low confidence commodity → both validation and matching run, 2 audit entries |
| `test_process_missing_required_field_returns_422` | Missing shipment_id → HTTP 422 with structured error body |

---

## API Endpoints

### `GET /health`

Returns service health and identity.

**Response:**
```json
{
  "status": "ok",
  "service": "document-intelligence",
  "version": "1.0.0"
}
```

### `POST /validate`

Runs validation checks only. No LLM call.

**Request body:** Full Execution Envelope (JSON)

**Response:** Envelope with `validation_results`, `decision`, and `audit` populated.

### `POST /match`

Runs LLM commodity matching only. No validation.

**Request body:** Full Execution Envelope (JSON)

**Response:** If matching was needed, envelope with `matching_results` and `audit` populated. If matching was not needed (commodity_code confidence >= threshold), returns envelope unchanged.

### `POST /process`

Full pipeline: validate → match (conditional) → deliver.

**Request body:** Full Execution Envelope (JSON)

**Response:** Fully enriched envelope with results from all executed stages.

---

## Design Principles

1. **Threshold from envelope, never hardcoded** — `confidence_threshold` is always read from `processing_instructions`. Different clients can send different thresholds without any code change.

2. **Audit is append-only** — Every stage appends to `envelope.audit`. No stage ever clears or replaces the list. This ensures a complete chronological trail.

3. **Business failures are not HTTP errors** — Low confidence scores, invalid dates, and missing commodity codes are expected business outcomes. They return HTTP 200 with a populated `decision` field. Only structurally malformed JSON returns HTTP 422.

4. **Graceful LLM degradation** — The LLM can be down, slow, or return garbage. The service always recovers: routes to human review, logs the error, and returns normally.

5. **Envelope is the unit of work** — Every service function takes an `Envelope` and returns an `Envelope`. No service takes individual fields. This keeps the contract simple and the audit trail intact.

6. **Pure service layer** — Services have zero HTTP imports. They contain pure business logic that's testable without starting a web server.

7. **LLM swap point** — The LLM integration is isolated in `_call_llm()` in `matching.py`. To switch providers, only that function and the underlying call need to change. Everything above it is LLM-agnostic.

---

## Setup & Running

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — add your GROQ_API_KEY, set USE_MOCK_LLM=false for real calls

# Run the service
uvicorn app.main:app --reload

# Run tests (no API key needed — LLM is mocked)
pytest -v
```

---

## What I Would Add Next

- Persistent audit trail (PostgreSQL with asyncpg)
- Multi-tenant configuration store (thresholds and rules per tenant_id)
- Async task queue for batch processing (Celery + Redis)
- OpenTelemetry traces with envelope_id as the span attribute
- Rate limiting per tenant_id
