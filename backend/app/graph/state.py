"""Pipeline state: what flows through the LangGraph.

One typed dict, mutated additively by each node. Plain dict (not Pydantic)
because LangGraph merges node returns into the state by key.
"""

from typing import Any, TypedDict

from app.contracts.decision import AdjudicationResult, ClaimDecision, FraudAssessment
from app.contracts.documents import ClassifiedDocument, DocumentIssue, ExtractedDocument
from app.contracts.inputs import ClaimInput
from app.observability.trace import TraceRecorder


class ClaimState(TypedDict, total=False):
    # --- Inputs (set once at graph entry) ---
    claim: ClaimInput
    policy: Any  # app.policy.loader.Policy — kept opaque to avoid import cycles
    trace: TraceRecorder
    llm: Any  # app.llm.client.LlmClient | None
    member_name: str

    # --- Node outputs ---
    classified_documents: list[ClassifiedDocument]
    document_issues: list[DocumentIssue]  # non-empty -> early stop
    llm_reads: dict[str, Any]  # file_id -> LlmDocumentRead (vision mode only)
    extracted_documents: list[ExtractedDocument]
    cross_validation_warnings: list[str]
    adjudication: AdjudicationResult
    fraud: FraudAssessment
    decision: ClaimDecision
