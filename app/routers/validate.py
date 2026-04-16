from fastapi import APIRouter

from app.models.envelope import Envelope
from app.services.validation import run_validation

router = APIRouter()


@router.post("/validate", response_model=Envelope)
async def validate_endpoint(envelope: Envelope):
    """
    Runs validation checks on the envelope.
    Returns HTTP 422 with structured error if the envelope itself is malformed.
    Returns HTTP 200 with enriched envelope for all business rule outcomes
    (including failed validations — those are not HTTP errors).
    """
    envelope = await run_validation(envelope)
    return envelope
