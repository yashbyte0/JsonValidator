def test_match_successful_llm_match(client, low_confidence_envelope_dict, mock_llm_success):
    """Test 4 — Successful LLM match returns enriched envelope."""
    response = client.post("/match", json=low_confidence_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["matching_results"] is not None
    assert data["matching_results"]["source"] == "llm_match"
    assert data["matching_results"]["matched_code"] == "8471.30.0100"
    assert data["matching_results"]["fallback_used"] is True
    assert len(data["audit"]) >= 1


def test_match_llm_timeout_graceful_degradation(
    client, low_confidence_envelope_dict, mock_llm_timeout
):
    """Test 5 — LLM timeout → graceful degradation, not 500."""
    response = client.post("/match", json=low_confidence_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["decision"]["route"] == "hitl_review"
    assert data["matching_results"]["source"] == "no_match"
    assert data["matching_results"]["fallback_used"] is False
    assert any(entry["result"] == "error" for entry in data["audit"])
