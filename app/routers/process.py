from fastapi import APIRouter

from app.models.envelope import Envelope
from app.services.validation import run_validation
from app.services.matching import run_matching

router = APIRouter()


@router.post("/process", response_model=Envelope)
async def process_endpoint(envelope: Envelope):
    """
    Full pipeline: validate → match (conditional) → return enriched envelope.
    The audit trail in the returned envelope must contain entries from all
    executed stages, in order.
    """
    # Stage 1: Always validate
    envelope = await run_validation(envelope)

    # Stage 2: Match only if commodity_code is missing or low confidence
    threshold = envelope.processing_instructions.confidence_threshold
    needs_match = (
        envelope.extraction.commodity_code is None
        or envelope.extraction.commodity_code.confidence < threshold
    )
    if needs_match:
        envelope = await run_matching(envelope)

    return envelope
