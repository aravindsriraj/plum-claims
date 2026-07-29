"""DecisionSynthesizer: combines adjudication + fraud + confidence into the
final decision. Deterministic precedence:

  1. Adjudication hard-fail          -> REJECTED (reasons from the engine)
  2. Fraud requires manual review    -> MANUAL_REVIEW (signals included)
  3. Some line items rejected        -> PARTIAL
  4. Otherwise                       -> APPROVED

Degradation never changes WHICH decision rules fire; it lowers confidence
and adds an advisory note recommending manual review (TC011).
"""

from app.contracts.decision import AdjudicationResult, ClaimDecision, FraudAssessment
from app.contracts.enums import Decision, LineItemStatus
from app.contracts.trace import ComponentFailure
from app.observability.trace import TraceRecorder

COMPONENT = "DecisionSynthesizer"

# Below this confidence, even a clean approval carries a manual-review advisory.
LOW_CONFIDENCE_THRESHOLD = 0.80


def synthesize(
    claimed_amount: float,
    adjudication: AdjudicationResult,
    fraud: FraudAssessment,
    confidence: float,
    failures: list[ComponentFailure],
    cross_validation_warnings: list[str],
    trace: TraceRecorder,
) -> ClaimDecision:
    degraded = bool(failures)
    notes: list[str] = []
    reasons: list[str] = []

    # --- Decide -----------------------------------------------------------
    if adjudication.hard_failed:
        decision = Decision.REJECTED
        approved = 0.0
        reasons = [c.reason for c in adjudication.checks if c.hard_fail and not c.passed]
    elif fraud.requires_manual_review:
        decision = Decision.MANUAL_REVIEW
        approved = 0.0
        reasons = [
            "Routed to manual review due to fraud/risk signals:",
            *[f"- {s.description}" for s in fraud.signals],
        ]
    elif any(li.status == LineItemStatus.REJECTED for li in adjudication.line_items):
        decision = Decision.PARTIAL
        approved = adjudication.approved_amount
        rejected_items = [
            li for li in adjudication.line_items if li.status == LineItemStatus.REJECTED
        ]
        reasons = [
            f"Approved ₹{approved:,.0f} of ₹{claimed_amount:,.0f}.",
            "Rejected line items:",
            *[f"- {li.description} (₹{li.amount:,.0f}): {li.rejection_reason}" for li in rejected_items],
        ]
    else:
        decision = Decision.APPROVED
        approved = adjudication.approved_amount
        reasons = [f"All checks passed. Approved ₹{approved:,.0f} of ₹{claimed_amount:,.0f}."]

    # --- Advisory notes ----------------------------------------------------
    if degraded:
        failed_components = ", ".join(f.component for f in failures)
        notes.append(
            f"Processing was incomplete: {failed_components} failed and was skipped. "
            f"Manual review is recommended before payout."
        )
    if decision == Decision.APPROVED and confidence < LOW_CONFIDENCE_THRESHOLD:
        notes.append(
            f"Confidence ({confidence:.2f}) is below {LOW_CONFIDENCE_THRESHOLD:.2f}; "
            f"manual review is recommended."
        )
    notes.extend(cross_validation_warnings)

    trace.record(
        COMPONENT,
        "DECISION",
        "PASS" if decision == Decision.APPROVED else "FAIL" if decision == Decision.REJECTED else "WARN",
        f"Decision: {decision.value} — approved ₹{approved:,.0f}, confidence {confidence:.2f}.",
        {"decision": decision.value, "approved": approved, "confidence": confidence},
    )

    return ClaimDecision(
        decision=decision,
        claimed_amount=claimed_amount,
        approved_amount=approved,
        confidence_score=confidence,
        reasons=reasons,
        rejection_reasons=adjudication.rejection_reasons,
        line_item_breakdown=adjudication.line_items,
        adjustments=adjudication.adjustments,
        fraud_signals=fraud.signals,
        degraded=degraded,
        component_failures=failures,
        notes=notes,
    )
