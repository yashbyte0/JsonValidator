from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class ExtractedField(BaseModel):
    """Represents a single extracted field with an OCR/ML confidence score."""
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class Extraction(BaseModel):
    """All fields extracted from the upstream document processing system."""
    shipment_id: ExtractedField
    ship_date: ExtractedField
    recipient_name: ExtractedField
    commodity_code: Optional[ExtractedField] = None
    commodity_desc: Optional[ExtractedField] = None


class ProcessingInstructions(BaseModel):
    """Client-specific workflow configuration. All thresholds come from here."""
    workflow: str
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    hitl_on_failure: bool


class TenantInfo(BaseModel):
    id: str
    name: str


class DocumentInfo(BaseModel):
    type: str
    filename: str
    page_count: int


class ValidationResult(BaseModel):
    passed: bool
    failed_fields: list[str]
    reasons: dict[str, str]


class MatchResult(BaseModel):
    matched_code: Optional[str]
    match_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    fallback_used: bool
    source: Literal["catalog_exact", "llm_match", "no_match"]


class Decision(BaseModel):
    route: Literal["auto_approve", "hitl_review", "rejected"]


class AuditEntry(BaseModel):
    timestamp: datetime
    service: str
    action: str
    envelope_id: str
    result: str
    details: dict


class Envelope(BaseModel):
    """The top-level execution envelope. This is the contract for all endpoints."""
    envelope_id: str
    schema_version: str
    tenant: TenantInfo
    document: DocumentInfo
    extraction: Extraction
    processing_instructions: ProcessingInstructions
    validation_results: Optional[ValidationResult] = None
    matching_results: Optional[MatchResult] = None
    decision: Optional[Decision] = None
    audit: list[AuditEntry] = Field(default_factory=list)
