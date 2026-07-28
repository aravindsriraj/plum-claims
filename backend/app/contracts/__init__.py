"""Public contract surface of the claims processing system.

Everything another engineer needs to reimplement any component without
reading its code is importable from here (see docs/CONTRACTS.md).
"""

from app.contracts.decision import (
    AdjudicationResult,
    Adjustment,
    ClaimDecision,
    FraudAssessment,
    FraudSignal,
    RuleCheck,
)
from app.contracts.documents import (
    ClassifiedDocument,
    DocumentIssue,
    ExtractedDocument,
    LineItem,
)
from app.contracts.enums import (
    AdjustmentKind,
    ClaimCategory,
    ClaimStatus,
    Decision,
    DocumentIssueCode,
    DocumentQuality,
    DocumentType,
    ExtractionMethod,
    LineItemStatus,
    TraceEventType,
    TraceStatus,
)
from app.contracts.inputs import ClaimInput, DocumentInput, PriorClaim
from app.contracts.responses import ClaimResponse, ProcessingMeta
from app.contracts.trace import ComponentFailure, TraceEvent

__all__ = [
    "AdjudicationResult",
    "Adjustment",
    "AdjustmentKind",
    "ClaimCategory",
    "ClaimDecision",
    "ClaimInput",
    "ClaimResponse",
    "ClaimStatus",
    "ClassifiedDocument",
    "ComponentFailure",
    "Decision",
    "DocumentInput",
    "DocumentIssue",
    "DocumentIssueCode",
    "DocumentQuality",
    "DocumentType",
    "ExtractedDocument",
    "ExtractionMethod",
    "FraudAssessment",
    "FraudSignal",
    "LineItem",
    "LineItemStatus",
    "PriorClaim",
    "ProcessingMeta",
    "RuleCheck",
    "TraceEvent",
    "TraceEventType",
    "TraceStatus",
]
