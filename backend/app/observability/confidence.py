"""Confidence model: a computed score, never an LLM self-assessment.

The score is a transparent multiplication of factors, each visible in the
trace:

    confidence = BASE
                 x mean(document extraction confidences)
                 x PI(component failure penalties)
                 x PI(data-quality penalties)

A clean claim with fully extracted content lands ~0.95+. A claim where a
component failed lands proportionally lower (TC011 requires exactly this).
The factors are constants, not learned, so the score is stable and
explainable.
"""

from app.contracts.documents import ExtractedDocument
from app.contracts.trace import ComponentFailure

BASE_CONFIDENCE = 0.98  # never claim 1.0 — some irreducible uncertainty always exists

# Data-quality penalties (multiplicative). Only fields that could change the
# DECISION are penalized — e.g. a missing bill total undermines amount
# verification, while a missing patient name is handled (and traced) by the
# cross-validation stage rather than silently eroding confidence here.
PENALTY_MISSING_BILL_TOTAL = 0.90


def compute_confidence(
    extracted_documents: list[ExtractedDocument],
    failures: list[ComponentFailure],
) -> float:
    """Compute the claim's confidence score from observable factors."""
    score = BASE_CONFIDENCE

    # Factor 1: how well did extraction go, on average?
    if extracted_documents:
        mean_extraction = sum(d.overall_confidence for d in extracted_documents) / len(
            extracted_documents
        )
        score *= mean_extraction

        # Factor 2: a bill without a readable total means amounts were never verified.
        for doc in extracted_documents:
            if doc.doc_type.value.endswith("BILL") and doc.total_amount is None:
                score *= PENALTY_MISSING_BILL_TOTAL

    # Factor 3: every failed component applies its declared penalty.
    for failure in failures:
        score *= 1.0 - failure.confidence_penalty

    return round(max(0.0, min(1.0, score)), 2)
