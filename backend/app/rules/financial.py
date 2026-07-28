"""Financial engine: turns an eligible amount into a payable amount.

Pure functions, no I/O, no LLM. The order of operations is contractual and
unit-tested (TC010 pins it):

    eligible_amount
      -> SUB_LIMIT_CAP      (category sub-limit, where applicable)
      -> NETWORK_DISCOUNT   (network hospital discount, BEFORE co-pay)
      -> COPAY              (member co-pay percentage)

Every step emits an Adjustment with before/after so the money math is fully
auditable in the trace.
"""

from pydantic import BaseModel

from app.contracts.decision import Adjustment
from app.contracts.enums import AdjustmentKind
from app.policy.loader import OpdCategoryRules
from app.rules.textnorm import normalize


class FinancialResult(BaseModel):
    eligible_amount: float
    approved_amount: float
    adjustments: list[Adjustment]
    network_hospital: bool
    notes: list[str] = []


def is_network_hospital(provider_name: str | None, network_hospitals: list[str]) -> bool:
    """Fuzzy membership check: exact or containment either way, normalized.

    'Apollo Hospitals' matches 'Apollo Hospitals, Bengaluru' and vice versa;
    'City Clinic, Bengaluru' matches nothing in the network list.
    """
    if not provider_name:
        return False
    candidate = normalize(provider_name)
    return any(
        normalize(h) and (normalize(h) in candidate or candidate in normalize(h))
        for h in network_hospitals
    )


def apply_sub_limit(
    amount: float, category: str, rules: OpdCategoryRules
) -> tuple[float, Adjustment | None]:
    """Cap `amount` at the category sub-limit where the sub-limit applies.

    Assumption (documented in ARCHITECTURE.md): for CONSULTATION claims the
    sub-limit applies to consultation-fee line items only — handled by the
    caller passing the consultation portion. For single-service categories
    (DENTAL, VISION, ALTERNATIVE_MEDICINE, DIAGNOSTIC, PHARMACY) the caller
    passes the full eligible amount.
    """
    if amount <= rules.sub_limit:
        return amount, None
    capped = float(rules.sub_limit)
    return capped, Adjustment(
        kind=AdjustmentKind.SUB_LIMIT_CAP,
        amount_before=amount,
        amount_after=capped,
        note=f"{category} sub-limit of ₹{rules.sub_limit:,.0f} applied "
        f"(₹{amount:,.0f} capped to ₹{capped:,.0f}).",
    )


def apply_network_discount(
    amount: float, network_hospital: bool, rules: OpdCategoryRules
) -> tuple[float, Adjustment | None]:
    """Network discount, applied BEFORE co-pay (TC010 pins this ordering)."""
    if not network_hospital or rules.network_discount_percent <= 0:
        return amount, None
    discounted = round(amount * (1 - rules.network_discount_percent / 100), 2)
    return discounted, Adjustment(
        kind=AdjustmentKind.NETWORK_DISCOUNT,
        amount_before=amount,
        amount_after=discounted,
        note=f"Network discount ({rules.network_discount_percent:.0f}%) applied: "
        f"₹{amount:,.0f} -> ₹{discounted:,.0f}.",
    )


def apply_copay(amount: float, rules: OpdCategoryRules) -> tuple[float, Adjustment | None]:
    """Member co-pay: the member bears this percentage of the post-discount amount."""
    if rules.copay_percent <= 0:
        return amount, None
    payable = round(amount * (1 - rules.copay_percent / 100), 2)
    return payable, Adjustment(
        kind=AdjustmentKind.COPAY,
        amount_before=amount,
        amount_after=payable,
        note=f"Co-pay ({rules.copay_percent:.0f}%) applied: member bears "
        f"₹{amount - payable:,.0f}, insurer pays ₹{payable:,.0f}.",
    )


def compute_payable(
    eligible_amount: float,
    category: str,
    rules: OpdCategoryRules,
    provider_name: str | None,
    network_hospitals: list[str],
) -> FinancialResult:
    """Run the full adjustment pipeline for one claim."""
    adjustments: list[Adjustment] = []
    notes: list[str] = []
    network = is_network_hospital(provider_name, network_hospitals)
    if network:
        notes.append(f"Provider '{provider_name}' is a network hospital.")

    amount, adj = apply_sub_limit(eligible_amount, category, rules)
    if adj:
        adjustments.append(adj)
    amount, adj = apply_network_discount(amount, network, rules)
    if adj:
        adjustments.append(adj)
    amount, adj = apply_copay(amount, rules)
    if adj:
        adjustments.append(adj)

    return FinancialResult(
        eligible_amount=eligible_amount,
        approved_amount=round(amount, 2),
        adjustments=adjustments,
        network_hospital=network,
        notes=notes,
    )
