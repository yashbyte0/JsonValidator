import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers import health, validate, match, process
from app.models.responses import ValidationErrorResponse, FieldError
from app.config import SERVICE_NAME, VERSION

import sys


class _EnvelopeIdFilter(logging.Filter):
    """Ensures 'envelope_id' is always available in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "envelope_id"):
            record.envelope_id = "N/A"
        return True


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s envelope_id=%(envelope_id)s %(message)s"
    )
)
_handler.addFilter(_EnvelopeIdFilter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[_handler],
)

app = FastAPI(
    title="Document Intelligence Platform",
    description="Validation and matching microservice for shipping document envelopes.",
    version=VERSION,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    failed = [
        FieldError(
            field=" → ".join(str(loc) for loc in e["loc"]),
            reason=e["msg"],
        )
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=ValidationErrorResponse(
            message="Request body failed schema validation",
            failed_fields=failed,
        ).model_dump(),
    )


app.include_router(health.router)
app.include_router(validate.router)
app.include_router(match.router)
app.include_router(process.router)
