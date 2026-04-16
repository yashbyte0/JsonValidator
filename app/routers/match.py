from fastapi import APIRouter

from app.models.envelope import Envelope
from app.services.matching import run_matching

router = APIRouter()


@router.post("/match", response_model=Envelope)
async def match_endpoint(envelope: Envelope):
    """
    Runs LLM commodity matching.
    Only calls the LLM if commodity_code confidence is below threshold.
    If commodity_code is None or its confidence < threshold, call matching service.
    Otherwise return envelope unchanged (matching not needed).
    """
    threshold = envelope.processing_instructions.confidence_threshold
    needs_match = (
        envelope.extraction.commodity_code is None
        or envelope.extraction.commodity_code.confidence < threshold
    )
    if needs_match:
        envelope = await run_matching(envelope)
    return envelope
