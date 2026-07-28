"""Decision contracts: adjudication results, fraud assessment, final decision."""

from pydantic import BaseModel, Field

from app.contracts.enums import AdjustmentKind, Decision
from app.contracts.documents import LineItem
from app.contracts.trace import ComponentFailure


class RuleCheck(BaseModel):
    """Outcome of one deterministic policy rule.

    `hard_fail=True` means the claim cannot be paid regardless of anything
    else (exclusion, waiting period, per-claim limit, missing pre-auth).
    """

    rule_id: str
    name: str
    passed: bool
    hard_fail: bool = False
    reason: str = Field(..., description="Human-readable explanation, shown in the trace")
    detail: dict = Field(default_factory=dict)


class Adjustment(BaseModel):
    """One step of the financial calculation.

    Adjustments are applied in `AdjustmentKind` order and each records
    before/after so the money math is fully auditable (TC010).
    """

    kind: AdjustmentKind
    amount_before: float
    amount_after: float
    note: str

    @property
    def delta(self) -> float:
        return round(self.amount_before - self.amount_after, 2)


class AdjudicationResult(BaseModel):
    """Output of the deterministic AdjudicationEngine."""

    checks: list[RuleCheck] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(
        default_factory=list,
        description="Machine codes, e.g. WAITING_PERIOD, PRE_AUTH_MISSING, "
        "PER_CLAIM_EXCEEDED, EXCLUDED_CONDITION",
    )
    eligible_amount: float = Field(default=0, description="Claimed amount minus ineligible line items")
    approved_amount: float = Field(default=0, description="Final payable amount after all adjustments")
    line_items: list[LineItem] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)

    @property
    def hard_failed(self) -> bool:
        return any(c.hard_fail and not c.passed for c in self.checks)


class FraudSignal(BaseModel):
    """One anomaly detected by the FraudAgent."""

    code: str = Field(..., examples=["SAME_DAY_VELOCITY", "HIGH_VALUE_CLAIM"])
    description: str
    severity: float = Field(..., ge=0, le=1, description="Contribution to the fraud score")


class FraudAssessment(BaseModel):
    fraud_score: float = Field(default=0.0, ge=0, le=1)
    signals: list[FraudSignal] = Field(default_factory=list)
    requires_manual_review: bool = False


class ClaimDecision(BaseModel):
    """The final, explainable decision returned for a processed claim."""

    decision: Decision
    claimed_amount: float
    approved_amount: float = 0
    confidence_score: float = Field(..., ge=0, le=1)

    reasons: list[str] = Field(
        default_factory=list, description="Why this decision was reached, in plain language"
    )
    rejection_reasons: list[str] = Field(default_factory=list)
    line_item_breakdown: list[LineItem] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    fraud_signals: list[FraudSignal] = Field(default_factory=list)

    degraded: bool = Field(
        default=False, description="True if any component failed and a fallback was used"
    )
    component_failures: list[ComponentFailure] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="Advisory notes, e.g. manual-review recommendation"
    )
