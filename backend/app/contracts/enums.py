"""Shared enumerations for the claims processing system.

Every component speaks in these enums. Keeping them in one place prevents
stringly-typed drift between agents, the rule engine, and the API.
"""

from enum import StrEnum


class ClaimCategory(StrEnum):
    """The type of treatment a member is claiming for.

    Maps 1:1 to keys in `policy_terms.json -> document_requirements` and
    (lower-cased) to `opd_categories`.
    """

    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(StrEnum):
    """Document types the pipeline can classify and extract from."""

    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"


class DocumentQuality(StrEnum):
    """How readable a document is, as judged by the classifier."""

    GOOD = "GOOD"
    LOW = "LOW"  # partially readable — extract best-effort, flag fields
    UNREADABLE = "UNREADABLE"  # cannot extract — member must re-upload


class Decision(StrEnum):
    """The four terminal claim decisions required by the assignment."""

    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ClaimStatus(StrEnum):
    """Top-level processing outcome for a submission.

    DOCUMENT_REJECTED — early-stop: documents unacceptable; no claim decision.
    DECIDED — pipeline finished with APPROVED/PARTIAL/REJECTED/MANUAL_REVIEW.
    AWAITING_HUMAN_REVIEW — HITL pause after MANUAL_REVIEW (CLAIMS_HITL=true).
    """

    DECIDED = "DECIDED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"


class DocumentIssueCode(StrEnum):
    """Machine-readable codes for early-stop document problems."""

    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    WRONG_DOCUMENT_TYPE = "WRONG_DOCUMENT_TYPE"
    UNREADABLE_DOCUMENT = "UNREADABLE_DOCUMENT"
    PATIENT_MISMATCH = "PATIENT_MISMATCH"


class TraceEventType(StrEnum):
    """What kind of thing a trace event describes."""

    CHECK = "CHECK"  # a deterministic rule/check was evaluated
    EXTRACTION = "EXTRACTION"  # data was extracted/classified from a document
    DECISION = "DECISION"  # a decision-relevant conclusion was reached
    ERROR = "ERROR"  # a component failed and a fallback was used
    INFO = "INFO"  # narrative context


class TraceStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"


class ExtractionMethod(StrEnum):
    """How a document's content was obtained.

    VISION_LLM       — a vision model read an actual uploaded file.
    PROVIDED_CONTENT — the caller supplied extracted content (eval/simulation).
    METADATA         — only type/quality metadata was available (eval cases
                       that test document verification, not extraction).
    """

    VISION_LLM = "VISION_LLM"
    PROVIDED_CONTENT = "PROVIDED_CONTENT"
    METADATA = "METADATA"


class LineItemStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AdjustmentKind(StrEnum):
    """Ordered financial adjustments. Order of application is contractual:
    sub-limit cap -> network discount -> co-pay -> per-claim cap."""

    SUB_LIMIT_CAP = "SUB_LIMIT_CAP"
    NETWORK_DISCOUNT = "NETWORK_DISCOUNT"
    COPAY = "COPAY"
    PER_CLAIM_CAP = "PER_CLAIM_CAP"
