"""Input contracts: what the outside world hands to the pipeline.

`ClaimInput` is the exact payload of `POST /claims`. It supports two document
modes deliberately:

1. Real uploads — `file_content_base64` carries an image/PDF and the
   ExtractionAgent reads it with a vision model.
2. Simulation/eval — `actual_type`, `quality`, `patient_name_on_doc` and/or
   `content` describe the document. This keeps the eval suite deterministic
   and lets test cases target specific pipeline stages.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.contracts.enums import ClaimCategory, DocumentQuality, DocumentType


class DocumentInput(BaseModel):
    """One uploaded document.

    Errors raised downstream if neither `file_content_base64` nor any
    simulation metadata is present: the DocumentVerificationAgent will
    classify it as UNKNOWN/UNREADABLE and the pipeline stops early.
    """

    file_id: str = Field(..., description="Caller-supplied stable identifier")
    file_name: str | None = Field(default=None, description="Original filename")
    file_content_base64: str | None = Field(
        default=None, description="Base64-encoded image/PDF for vision extraction"
    )
    mime_type: str | None = Field(default=None, examples=["image/jpeg", "application/pdf"])
    declared_type: DocumentType | None = Field(
        default=None, description="What the member says this document is (optional)"
    )

    # --- Simulation / eval fields (ignored when file_content_base64 is set) ---
    actual_type: DocumentType | None = Field(
        default=None, description="Ground-truth type, used by the eval harness"
    )
    quality: DocumentQuality | None = Field(
        default=None, description="Ground-truth readability, used by the eval harness"
    )
    patient_name_on_doc: str | None = Field(
        default=None, description="Ground-truth patient name, used by the eval harness"
    )
    content: dict[str, Any] | None = Field(
        default=None, description="Pre-extracted structured content, used by the eval harness"
    )


class PriorClaim(BaseModel):
    """A historical claim, used by the FraudAgent for velocity checks."""

    claim_id: str
    date: date
    amount: float = Field(..., ge=0)
    provider: str | None = None


class ClaimInput(BaseModel):
    """A complete claim submission.

    Validation errors (raised as 422 by the API):
      - claimed_amount <= 0
      - no documents attached
      - treatment_date in the future
    """

    member_id: str = Field(..., examples=["EMP001"])
    policy_id: str = Field(..., examples=["PLUM_GHI_2024"])
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: float = Field(..., gt=0)
    hospital_name: str | None = Field(
        default=None, description="Provider name if known at submission time"
    )
    pre_auth_reference: str | None = Field(
        default=None,
        description="Pre-authorization reference number, if the member obtained one. "
        "Required for high-value diagnostics and planned procedures per policy.",
    )
    ytd_claims_amount: float = Field(
        default=0, ge=0, description="Member's year-to-date claimed amount"
    )
    claims_history: list[PriorClaim] = Field(default_factory=list)
    documents: list[DocumentInput] = Field(..., min_length=1)
    simulate_component_failure: bool = Field(
        default=False,
        description="Fault-injection hook: forces one pipeline component to fail "
        "so graceful degradation can be exercised (used by TC011).",
    )
    submission_date: date | None = Field(
        default=None,
        description="When the claim was submitted. If omitted, the submission-deadline "
        "rule is skipped and marked NOT_EVALUATED (eval cases omit it deliberately).",
    )

    @model_validator(mode="after")
    def treatment_not_in_future(self) -> "ClaimInput":
        # Claims for future treatment are never valid; catch bad input at the door.
        if self.submission_date and self.treatment_date > self.submission_date:
            raise ValueError("treatment_date cannot be after submission_date")
        return self
