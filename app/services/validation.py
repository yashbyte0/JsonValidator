import logging
from datetime import datetime, date, timezone, timedelta

from app.models.envelope import (
    Envelope,
    ValidationResult,
    Decision,
    AuditEntry,
)

logger = logging.getLogger(__name__)

# Field names used for confidence checking
_CONFIDENCE_FIELDS = [
    "shipment_id",
    "ship_date",
    "recipient_name",
    "commodity_code",
    "commodity_desc",
]


async def run_validation(envelope: Envelope) -> Envelope:
    """
    Runs all validation checks. Returns enriched envelope with:
    - validation_results populated
    - decision.route set
    - audit entry appended
    Never raises exceptions for business rule failures.
    """
    logger.info("Starting validation", extra={"envelope_id": envelope.envelope_id})

    threshold = envelope.processing_instructions.confidence_threshold
    failed_fields: list[str] = []
    reasons: dict[str, str] = {}

    # 6a. Schema check — required fields must be present and non-empty
    if not envelope.extraction.shipment_id.value:
        field_name = "shipment_id"
        failed_fields.append(field_name)
        reasons[field_name] = "Required field shipment_id is missing or empty"
        logger.warning(
            "Required field missing or empty",
            extra={"envelope_id": envelope.envelope_id, "field": field_name},
        )

    if not envelope.extraction.recipient_name.value:
        field_name = "recipient_name"
        failed_fields.append(field_name)
        reasons[field_name] = "Required field recipient_name is missing or empty"
        logger.warning(
            "Required field missing or empty",
            extra={"envelope_id": envelope.envelope_id, "field": field_name},
        )

    if (
        envelope.extraction.commodity_code is None
        and envelope.extraction.commodity_desc is None
    ):
        field_name = "commodity"
        failed_fields.append(field_name)
        reasons[field_name] = (
            "At least one of commodity_code or commodity_desc must be present"
        )
        logger.warning(
            "No commodity field present",
            extra={"envelope_id": envelope.envelope_id, "field": field_name},
        )

    # 6b. Confidence check — compare each field's confidence against threshold
    for field_name in _CONFIDENCE_FIELDS:
        field = getattr(envelope.extraction, field_name, None)
        if field is not None and field.confidence < threshold:
            failed_fields.append(field_name)
            reason = f"Confidence {field.confidence} below threshold {threshold}"
            reasons[field_name] = reason
            logger.warning(
                "Field failed confidence check",
                extra={
                    "envelope_id": envelope.envelope_id,
                    "field": field_name,
                    "confidence": field.confidence,
                },
            )

    # 6c. Date validation
    try:
        ship_date = date.fromisoformat(envelope.extraction.ship_date.value)
        today = date.today()
        if ship_date > today:
            field_name = "ship_date"
            failed_fields.append(field_name)
            reasons[field_name] = "Ship date is in the future"
            logger.warning(
                "Ship date is in the future",
                extra={
                    "envelope_id": envelope.envelope_id,
                    "field": field_name,
                    "ship_date": str(ship_date),
                },
            )
        elif ship_date < today - timedelta(days=365):
            field_name = "ship_date"
            failed_fields.append(field_name)
            reasons[field_name] = "Ship date is older than 365 days"
            logger.warning(
                "Ship date is older than 365 days",
                extra={
                    "envelope_id": envelope.envelope_id,
                    "field": field_name,
                    "ship_date": str(ship_date),
                },
            )
    except ValueError:
        field_name = "ship_date"
        failed_fields.append(field_name)
        reasons[field_name] = "Invalid date format, expected YYYY-MM-DD"
        logger.warning(
            "Invalid date format",
            extra={
                "envelope_id": envelope.envelope_id,
                "field": field_name,
            },
        )

    # 6d. Decision routing
    if not failed_fields:
        route = "auto_approve"
    elif envelope.processing_instructions.hitl_on_failure:
        route = "hitl_review"
    else:
        route = "rejected"

    envelope.validation_results = ValidationResult(
        passed=len(failed_fields) == 0,
        failed_fields=failed_fields,
        reasons=reasons,
    )
    envelope.decision = Decision(route=route)

    # 6e. Audit entry
    audit_entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        service="validation-service",
        action="validate_envelope",
        envelope_id=envelope.envelope_id,
        result="passed" if not failed_fields else "failed",
        details={"failed_fields": failed_fields, "reasons": reasons},
    )
    envelope.audit.append(audit_entry)

    logger.info(
        "Validation complete",
        extra={
            "envelope_id": envelope.envelope_id,
            "passed": envelope.validation_results.passed,
            "route": route,
        },
    )

    return envelope
