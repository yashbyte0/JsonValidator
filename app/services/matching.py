# =============================================================================
# LLM SWAP POINT
# -----------------------------------------------------------------------------
# By default this service calls the Groq API (OpenAI-compatible endpoint).
# To use a mock instead (for testing or when no API key is available):
#   1. Set environment variable: USE_MOCK_LLM=true
#   2. The mock function `_mock_llm_response()` below returns a deterministic
#      match for any description containing "data processing" → 8471.30.0100
#
# To switch providers: replace `_call_groq()` with your preferred implementation.
# The swap point is the single function `_call_llm(desc: str) -> str`.
# Everything above it in the pipeline is LLM-agnostic.
# =============================================================================

import os
import json
import logging
from datetime import datetime, timezone

import httpx

from app.models.envelope import (
    Envelope,
    MatchResult,
    Decision,
    AuditEntry,
)

logger = logging.getLogger(__name__)

COMMODITY_CATALOG: list[dict] = [
    {
        "hs_code": "8471.30.0100",
        "description": "Portable automatic data processing machines, weight ≤ 10kg (laptops, notebooks)",
        "category": "Electronics",
        "restricted": False,
        "typical_weight_kg": 1.8,
    },
    {
        "hs_code": "8471.41.0100",
        "description": "Data processing machines: comprising a central processing unit and input/output unit (desktops)",
        "category": "Electronics",
        "restricted": False,
        "typical_weight_kg": 6.5,
    },
    {
        "hs_code": "8517.12.0000",
        "description": "Mobile phones and smartphones for cellular networks",
        "category": "Telecommunications",
        "restricted": False,
        "typical_weight_kg": 0.2,
    },
    {
        "hs_code": "9403.30.0000",
        "description": "Wooden office furniture (desks, shelving, filing cabinets)",
        "category": "Furniture",
        "restricted": False,
        "typical_weight_kg": 22.0,
    },
    {
        "hs_code": "3004.90.9200",
        "description": "Medicaments for human use, mixed or unmixed, in measured doses",
        "category": "Pharmaceuticals",
        "restricted": True,
        "typical_weight_kg": 0.5,
    },
    {
        "hs_code": "6204.62.4010",
        "description": "Women's denim trousers and jeans of cotton",
        "category": "Apparel",
        "restricted": False,
        "typical_weight_kg": 0.6,
    },
    {
        "hs_code": "8703.23.0000",
        "description": "Passenger motor vehicles with engine displacement 1500–3000cc",
        "category": "Automotive",
        "restricted": True,
        "typical_weight_kg": 1400.0,
    },
    {
        "hs_code": "0901.11.0000",
        "description": "Coffee, not roasted, not decaffeinated (green coffee beans)",
        "category": "Agricultural",
        "restricted": False,
        "typical_weight_kg": 60.0,
    },
    {
        "hs_code": "8544.42.9000",
        "description": "Insulated electrical conductors, fitted with connectors (power cables, USB cables)",
        "category": "Electronics",
        "restricted": False,
        "typical_weight_kg": 0.3,
    },
    {
        "hs_code": "9018.19.9560",
        "description": "Medical diagnostic instruments: patient monitoring devices, ECG machines",
        "category": "Medical Devices",
        "restricted": True,
        "typical_weight_kg": 2.1,
    },
]

MATCH_PROMPT_TEMPLATE = """
You are a customs classification expert. Your job is to match a commodity description to the best Harmonized System (HS) code from a provided catalog.

COMMODITY DESCRIPTION TO CLASSIFY:
{commodity_desc}

REFERENCE CATALOG (JSON):
{catalog_json}

Instructions:
- Identify the single best matching HS code from the catalog above.
- If no entry is a reasonable match, set matched_code to null and source to "no_match".
- Respond with ONLY a valid JSON object. No preamble, no explanation outside the JSON.
- Do not wrap the JSON in markdown code blocks.

Required JSON structure:
{{
  "matched_code": "<hs_code string or null>",
  "match_confidence": <float between 0.0 and 1.0>,
  "rationale": "<one sentence explaining why this is the best match>",
  "fallback_used": true,
  "source": "<'llm_match' if matched, 'no_match' if nothing matched>"
}}
"""


async def _call_groq(commodity_desc: str) -> str:
    """Call the Groq API to classify a commodity description."""
    api_key = os.getenv("GROQ_API_KEY")
    catalog_json = json.dumps(COMMODITY_CATALOG, indent=2)
    prompt = MATCH_PROMPT_TEMPLATE.format(
        commodity_desc=commodity_desc,
        catalog_json=catalog_json,
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _mock_llm_response(commodity_desc: str) -> str:
    """
    Deterministic mock for testing. Returns a JSON string.
    Matches 'data processing' → 8471.30.0100.
    Matches nothing else → no_match.
    """
    desc_lower = commodity_desc.lower()
    if (
        "data processing" in desc_lower
        or "laptop" in desc_lower
        or "notebook" in desc_lower
    ):
        return json.dumps(
            {
                "matched_code": "8471.30.0100",
                "match_confidence": 0.91,
                "rationale": "Description matches portable automatic data processing machines under 10kg.",
                "fallback_used": True,
                "source": "llm_match",
            }
        )
    return json.dumps(
        {
            "matched_code": None,
            "match_confidence": 0.0,
            "rationale": "No matching entry found in the reference catalog.",
            "fallback_used": True,
            "source": "no_match",
        }
    )


async def _call_llm(commodity_desc: str) -> str:
    """Swap point: calls the real LLM or the mock based on env var."""
    use_mock = os.getenv("USE_MOCK_LLM", "false").lower() in ("true", "1", "yes")
    if use_mock:
        return await _mock_llm_response(commodity_desc)
    return await _call_groq(commodity_desc)


async def run_matching(envelope: Envelope) -> Envelope:
    """
    Run LLM commodity matching on the envelope.
    Gracefully degrades on any failure — never re-raises.
    """
    commodity_desc = ""
    if envelope.extraction.commodity_desc is not None:
        commodity_desc = envelope.extraction.commodity_desc.value
    elif envelope.extraction.commodity_code is not None:
        commodity_desc = envelope.extraction.commodity_code.value

    logger.info(
        "Starting commodity matching",
        extra={
            "envelope_id": envelope.envelope_id,
            "input_desc": commodity_desc[:80],
        },
    )

    try:
        raw_response = await _call_llm(commodity_desc)
        parsed = json.loads(raw_response)

        match_result = MatchResult(
            matched_code=parsed.get("matched_code"),
            match_confidence=parsed.get("match_confidence", 0.0),
            rationale=parsed.get("rationale", ""),
            fallback_used=parsed.get("fallback_used", True),
            source=parsed.get("source", "no_match"),
        )
        envelope.matching_results = match_result

        # 8e. Post-match decision override
        if match_result.match_confidence < 0.70:
            envelope.decision = Decision(route="hitl_review")

        result_status = "matched" if match_result.source == "llm_match" else "no_match"

        audit_entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            service="matching-service",
            action="llm_commodity_match",
            envelope_id=envelope.envelope_id,
            result=result_status,
            details={
                "input_desc": commodity_desc,
                "matched_code": match_result.matched_code,
                "match_confidence": match_result.match_confidence,
                "source": match_result.source,
            },
        )
        envelope.audit.append(audit_entry)

        logger.info(
            "Matching complete",
            extra={
                "envelope_id": envelope.envelope_id,
                "matched_code": match_result.matched_code,
                "source": match_result.source,
            },
        )

    except (
        httpx.TimeoutException,
        httpx.HTTPError,
        json.JSONDecodeError,
        Exception,
    ) as exc:
        logger.error(
            "LLM call failed",
            extra={
                "envelope_id": envelope.envelope_id,
                "error": str(exc),
            },
        )

        envelope.matching_results = MatchResult(
            matched_code=None,
            match_confidence=0.0,
            rationale="LLM call failed",
            fallback_used=False,
            source="no_match",
        )
        envelope.decision = Decision(route="hitl_review")

        audit_entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            service="matching-service",
            action="llm_commodity_match",
            envelope_id=envelope.envelope_id,
            result="error",
            details={
                "error": str(exc),
                "action": "llm_call_failed",
            },
        )
        envelope.audit.append(audit_entry)

    return envelope
