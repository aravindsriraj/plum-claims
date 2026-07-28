"""Fraud detection: deterministic velocity and value signals.

Fraud scoring is rule-based (thresholds from policy_terms.json), not an LLM
judgment call — the signals and their thresholds are exactly what an
operations team would check by hand, so the output is inherently explainable.
"""

from datetime import date

from app.contracts.decision import FraudAssessment, FraudSignal
from app.contracts.inputs import PriorClaim

# Severity weights per signal. Stacked and capped at 1.0 to form fraud_score.
SEVERITY_SAME_DAY_VELOCITY = 0.70
SEVERITY_MONTHLY_VELOCITY = 0.40
SEVERITY_HIGH_VALUE = 0.30


def assess_fraud(
    member_id: str,
    treatment_date: date,
    claimed_amount: float,
    claims_history: list[PriorClaim],
    thresholds: dict,
) -> FraudAssessment:
    """Evaluate fraud signals for one claim against the member's history.

    Manual review is triggered when: a velocity limit is breached, the claim
    value crosses the auto-review amount, or the stacked fraud score reaches
    the policy's manual-review threshold.
    """
    signals: list[FraudSignal] = []

    # Signal 1: same-day velocity. `claims_history` holds PRIOR claims only;
    # this submission is the +1.
    same_day_count = sum(1 for c in claims_history if c.date == treatment_date) + 1
    same_day_limit = int(thresholds["same_day_claims_limit"])
    if same_day_count > same_day_limit:
        signals.append(
            FraudSignal(
                code="SAME_DAY_VELOCITY",
                description=(
                    f"This is claim #{same_day_count} from member {member_id} on "
                    f"{treatment_date.isoformat()} (policy limit: {same_day_limit}/day). "
                    f"Prior same-day claims: "
                    + ", ".join(
                        f"{c.claim_id} ₹{c.amount:,.0f} at {c.provider or 'unknown provider'}"
                        for c in claims_history
                        if c.date == treatment_date
                    )
                ),
                severity=SEVERITY_SAME_DAY_VELOCITY,
            )
        )

    # Signal 2: monthly velocity.
    monthly_count = (
        sum(
            1
            for c in claims_history
            if c.date.year == treatment_date.year and c.date.month == treatment_date.month
        )
        + 1
    )
    monthly_limit = int(thresholds["monthly_claims_limit"])
    if monthly_count > monthly_limit:
        signals.append(
            FraudSignal(
                code="MONTHLY_VELOCITY",
                description=(
                    f"Claim #{monthly_count} this calendar month "
                    f"(policy limit: {monthly_limit}/month)."
                ),
                severity=SEVERITY_MONTHLY_VELOCITY,
            )
        )

    # Signal 3: unusually high claim value.
    high_value_threshold = float(thresholds["high_value_claim_threshold"])
    if claimed_amount >= high_value_threshold:
        signals.append(
            FraudSignal(
                code="HIGH_VALUE_CLAIM",
                description=(
                    f"Claimed amount ₹{claimed_amount:,.0f} meets/exceeds the high-value "
                    f"threshold of ₹{high_value_threshold:,.0f}."
                ),
                severity=SEVERITY_HIGH_VALUE,
            )
        )

    fraud_score = min(1.0, sum(s.severity for s in signals))
    requires_manual_review = (
        any(s.code in ("SAME_DAY_VELOCITY", "MONTHLY_VELOCITY") for s in signals)
        or claimed_amount >= float(thresholds["auto_manual_review_above"])
        or fraud_score >= float(thresholds["fraud_score_manual_review_threshold"])
    )

    return FraudAssessment(
        fraud_score=round(fraud_score, 2),
        signals=signals,
        requires_manual_review=requires_manual_review,
    )
