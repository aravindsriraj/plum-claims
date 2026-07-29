"""Financial engine: turns an eligible amount into a payable amount.

Pure functions, no I/O, no LLM. The order of operations is contractual and
unit-tested (TC010 pins it):

    eligible_amount
      -> SUB_LIMIT_CAP      (category sub-limit, where applicable)
      -> NETWORK_DISCOUNT   (network hospital discount, BEFORE co-pay)
      -> COPAY              (member co-pay percentage)

Every step emits an Adjustment with before/after so the money math is fully
auditable in the trace. The adjudication engine orchestrates the steps; this
module owns only the arithmetic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.contracts.decision import Adjustment
from app.contracts.enums import AdjustmentKind
from app.policy.loader import OpdCategoryRules
from app.rules.textnorm import normalize

if TYPE_CHECKING:
    from app.llm.client import LlmClient


def is_network_hospital(
    provider_name: str | None,
    network_hospitals: list[str],
    llm: LlmClient | None = None,
) -> bool:
    """Fuzzy membership check: exact or containment either way, normalized, with LLM fallback.

    'Apollo Hospitals' matches 'Apollo Hospitals, Bengaluru' and vice versa;
    'City Clinic, Bengaluru' matches nothing in the network list.
    """
    if not provider_name:
        return False
    candidate = normalize(provider_name)
    if not candidate:
        return False
    for hospital in network_hospitals:
        name = normalize(hospital)
        if name and (name in candidate or candidate in name):
            return True

    if llm is not None:
        try:
            from pydantic import BaseModel, Field
            from app.llm.prompts import PROVIDER_RECONCILIATION_PROMPT

            class NetworkHospitalMatch(BaseModel):
                same_provider: bool = Field(description="True if provider matches any network hospital entity or branch")

            prompt = (
                f"Determine if the provider name '{provider_name}' matches any network hospital listed below.\n\n"
                f"NETWORK HOSPITALS LIST:\n"
                + "\n".join(f"- {h}" for h in network_hospitals)
                + "\n\nReturn same_provider=true if it is a branch, affiliate, or alias of a network hospital."
            )
            res = llm.structured(NetworkHospitalMatch, prompt)
            if res and res.same_provider:
                return True
        except Exception:
            pass

    return False


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
