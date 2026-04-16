import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def base_envelope_dict() -> dict:
    """A valid envelope where all fields pass threshold 0.80."""
    return {
        "envelope_id": "env_test_001",
        "schema_version": "envelope-v1",
        "tenant": {"id": "test_tenant", "name": "Test Tenant Inc."},
        "document": {
            "type": "shipping_manifest",
            "filename": "test.pdf",
            "page_count": 1,
        },
        "extraction": {
            "shipment_id": {"value": "SHP-2026-001", "confidence": 0.95},
            "ship_date": {"value": "2026-01-15", "confidence": 0.92},
            "recipient_name": {"value": "Acme Corp", "confidence": 0.90},
            "commodity_code": {"value": "8471.30.0100", "confidence": 0.88},
            "commodity_desc": {"value": "portable laptop computer", "confidence": 0.97},
        },
        "processing_instructions": {
            "workflow": "manifest-v1",
            "confidence_threshold": 0.80,
            "hitl_on_failure": True,
        },
        "validation_results": None,
        "matching_results": None,
        "decision": None,
        "audit": [],
    }


@pytest.fixture
def low_confidence_envelope_dict(base_envelope_dict) -> dict:
    """Envelope where recipient_name and commodity_code are below threshold."""
    env = base_envelope_dict.copy()
    env["extraction"] = dict(base_envelope_dict["extraction"])
    env["extraction"]["recipient_name"] = {
        "value": "Johansson & Bäckström AB",
        "confidence": 0.71,
    }
    env["extraction"]["commodity_code"] = {
        "value": "8471.30.0100",
        "confidence": 0.58,
    }
    return env


@pytest.fixture
def missing_shipment_id_dict(base_envelope_dict) -> dict:
    """Envelope missing required shipment_id — should cause HTTP 422."""
    env = base_envelope_dict.copy()
    env["extraction"] = dict(base_envelope_dict["extraction"])
    del env["extraction"]["shipment_id"]
    return env


@pytest.fixture
def mock_llm_success():
    """Patches the LLM call to return a successful deterministic match."""
    mock_response = json.dumps(
        {
            "matched_code": "8471.30.0100",
            "match_confidence": 0.91,
            "rationale": "Description matches portable automatic data processing machines.",
            "fallback_used": True,
            "source": "llm_match",
        }
    )
    with patch(
        "app.services.matching._call_llm",
        new=AsyncMock(return_value=mock_response),
    ):
        yield


@pytest.fixture
def mock_llm_timeout():
    """Patches the LLM call to raise a timeout exception."""
    with patch(
        "app.services.matching._call_llm",
        new=AsyncMock(side_effect=httpx.TimeoutException("LLM timed out")),
    ):
        yield


@pytest.fixture
def client():
    return TestClient(app)
