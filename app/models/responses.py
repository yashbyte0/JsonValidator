from pydantic import BaseModel


class FieldError(BaseModel):
    field: str
    reason: str


class ValidationErrorResponse(BaseModel):
    error: str = "validation_failed"
    message: str
    failed_fields: list[FieldError]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
