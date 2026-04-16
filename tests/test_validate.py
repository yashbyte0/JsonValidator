def test_validate_happy_path_auto_approve(client, base_envelope_dict):
    """Test 1 — Happy path: all fields above threshold → auto_approve."""
    response = client.post("/validate", json=base_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["decision"]["route"] == "auto_approve"
    assert data["validation_results"]["passed"] is True
    assert data["validation_results"]["failed_fields"] == []
    assert len(data["audit"]) == 1
    assert data["audit"][0]["service"] == "validation-service"


def test_validate_low_confidence_hitl_review(client, low_confidence_envelope_dict):
    """Test 2 — Low confidence fields → hitl_review."""
    response = client.post("/validate", json=low_confidence_envelope_dict)

    assert response.status_code == 200
    data = response.json()

    assert data["decision"]["route"] == "hitl_review"
    assert data["validation_results"]["passed"] is False
    assert "recipient_name" in data["validation_results"]["failed_fields"]
    assert "commodity_code" in data["validation_results"]["failed_fields"]
    assert data["audit"][0]["result"] == "failed"


def test_validate_hitl_on_failure_false_rejected(client, low_confidence_envelope_dict):
    """Test 3 — hitl_on_failure=false → rejected route."""
    env = low_confidence_envelope_dict.copy()
    env["processing_instructions"] = dict(env["processing_instructions"])
    env["processing_instructions"]["hitl_on_failure"] = False

    response = client.post("/validate", json=env)

    assert response.status_code == 200
    data = response.json()

    assert data["decision"]["route"] == "rejected"
