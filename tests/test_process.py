def test_process_full_pipeline_happy_path(client, base_envelope_dict, mock_llm_success):
    """Test 6 — Full pipeline: all fields above threshold → auto_approve, no matching."""
    response = client.post("/process", json=base_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["decision"]["route"] == "auto_approve"
    assert data["validation_results"] is not None
    assert data["matching_results"] is None
    assert len(data["audit"]) == 1  # validation only


def test_process_full_pipeline_triggers_matching(
    client, low_confidence_envelope_dict, mock_llm_success
):
    """Test 7 — Full pipeline with low confidence commodity_code triggers matching."""
    response = client.post("/process", json=low_confidence_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["validation_results"] is not None
    assert data["matching_results"] is not None
    assert len(data["audit"]) == 2  # validation + matching


def test_process_missing_required_field_returns_422(client, missing_shipment_id_dict):
    """Test 8 — Missing shipment_id → HTTP 422 with structured error."""
    response = client.post("/process", json=missing_shipment_id_dict)

    assert response.status_code == 422
    data = response.json()

    assert "error" in data
    assert "failed_fields" in data
    assert isinstance(data["failed_fields"], list)
    assert len(data["failed_fields"]) > 0
