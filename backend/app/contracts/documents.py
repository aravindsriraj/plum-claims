"""Document-processing contracts.

These are the outputs of the DocumentVerificationAgent and ExtractionAgent —
the two components that turn raw uploads into structured, validated data.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.contracts.enums import (
    DocumentIssueCode,
    DocumentQuality,
    DocumentType,
    ExtractionMethod,
)


class ClassifiedDocument(BaseModel):
    """The verification agent's view of one uploaded document.

    Produced for EVERY upload, before any extraction is attempted.
    """

    file_id: str
    file_name: str | None = None
    detected_type: DocumentType = DocumentType.UNKNOWN
    detection_confidence: float = Field(default=0.0, ge=0, le=1)
    quality: DocumentQuality = DocumentQuality.GOOD
    patient_name_on_doc: str | None = None
    method: ExtractionMethod


class DocumentIssue(BaseModel):
    """A specific, member-actionable problem with the uploaded documents.

    The `message` field is contractual: it must name what was found and what
    is needed instead, precisely enough that the member knows what to do next
    (assignment requirement #2 / TC001-TC003).
    """

    code: DocumentIssueCode
    file_id: str | None = None
    message: str
    found: str | None = Field(default=None, description="What was actually uploaded/found")
    expected: str | None = Field(default=None, description="What is required instead")


class LineItem(BaseModel):
    """One billed line. Carries adjudication outcome after the rule engine runs."""

    description: str
    amount: float = Field(..., ge=0)
    status: str = Field(default="PENDING", description="PENDING | APPROVED | REJECTED")
    rejection_reason: str | None = None
    approved_amount: float | None = None


class ExtractedDocument(BaseModel):
    """Structured content of one document, produced by the ExtractionAgent.

    All fields are optional because real documents are messy; anything the
    extractor could not read is listed in `unreadable_fields` and its absence
    is reflected in `overall_confidence` rather than silently defaulted.
    """

    file_id: str
    doc_type: DocumentType
    method: ExtractionMethod

    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    provider_name: str | None = Field(
        default=None, description="Hospital / clinic / lab / pharmacy name"
    )
    document_date: date | None = None

    diagnosis: str | None = None
    treatment: str | None = None
    medicines: list[str] = Field(default_factory=list)
    tests_ordered: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    total_amount: float | None = Field(default=None, ge=0)

    overall_confidence: float = Field(default=1.0, ge=0, le=1)
    unreadable_fields: list[str] = Field(default_factory=list)
    raw_content: dict[str, Any] = Field(
        default_factory=dict, description="Source content (provided mode) or raw LLM JSON"
    )
