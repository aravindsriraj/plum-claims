"""API response contract: the complete output of processing one claim."""

from pydantic import BaseModel, Field

from app.contracts.decision import ClaimDecision
from app.contracts.documents import DocumentIssue
from app.contracts.enums import ClaimStatus
from app.contracts.trace import TraceEvent


class ProcessingMeta(BaseModel):
    duration_ms: int
    degraded: bool = False
    llm_calls: int = Field(default=0, description="How many LLM calls this claim required")


class ClaimResponse(BaseModel):
    """Top-level response of POST /claims.

    - status=DOCUMENT_REJECTED: pipeline stopped early; `document_issues` tells
      the member exactly what to fix. `decision` is None by design — no claim
      decision was made.
    - status=DECIDED: `decision` carries one of APPROVED/PARTIAL/REJECTED/
      MANUAL_REVIEW plus the full audit trail.
    """

    claim_id: str
    status: ClaimStatus
    member_message: str = Field(
        ..., description="Single member-facing summary of what happened and what to do next"
    )
    document_issues: list[DocumentIssue] = Field(default_factory=list)
    decision: ClaimDecision | None = None
    explanation: str = Field(
        default="", description="Ops-readable narrative generated from the trace"
    )
    trace: list[TraceEvent] = Field(default_factory=list)
    processing: ProcessingMeta
