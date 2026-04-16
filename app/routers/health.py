from fastapi import APIRouter

from app.config import SERVICE_NAME, VERSION
from app.models.responses import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
    )
