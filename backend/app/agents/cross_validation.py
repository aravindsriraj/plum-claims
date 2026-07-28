"""CrossValidationAgent: consistency checks ACROSS documents and claim.

Nothing here can reject a claim outright — inconsistencies reduce confidence
and can route to manual review via soft signals. Hard stops for identity
problems already happened in DocumentVerificationAgent.

Checks:
  1. Patient name on documents vs member roster name.
  2. Document dates vs the claimed treatment date.
  3. Bill total vs the claimed amount.
  4. Prescription requirement (category rules) — is a prescription among the
     extracted docs when the category mandates one?
"""

from app.contracts.documents import ExtractedDocument
from app.contracts.inputs import ClaimInput
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.textnorm import normalize

COMPONENT = "CrossValidationAgent"

# How far apart a document date and the claimed treatment date may be before
# we flag it. Small gaps happen (report issued next day); big ones are odd.
DATE_TOLERANCE_DAYS = 3


def cross_validate(
    claim: ClaimInput,
    member_name: str,
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
) -> list[str]:
    """Run consistency checks. Returns soft-warning strings for the trace and
    (via the caller) the decision notes. Never raises on data problems."""
    warnings: list[str] = []
    rules = policy.category_rules(claim.claim_category)

    # 1. Patient identity across extracted content.
    doc_names = [d.patient_name for d in docs if d.patient_name]
    if doc_names:
        member_norm = normalize(member_name)
        mismatched = [n for n in doc_names if normalize(n) != member_norm]
        if mismatched:
            warnings.append(
                f"Extracted patient name(s) {mismatched} do not match member "
                f"'{member_name}'."
            )
            trace.warn(COMPONENT, warnings[-1])
        else:
            trace.check(COMPONENT, True, f"Patient name '{member_name}' consistent across documents.")
    else:
        warnings.append("No patient name could be extracted from any document.")
        trace.warn(COMPONENT, warnings[-1])

    # 2. Document dates vs treatment date.
    for d in docs:
        if d.document_date is None:
            continue
        gap = abs((d.document_date - claim.treatment_date).days)
        if gap > DATE_TOLERANCE_DAYS:
            warnings.append(
                f"{d.file_id} is dated {d.document_date.isoformat()}, {gap} days from "
                f"the claimed treatment date {claim.treatment_date.isoformat()}."
            )
            trace.warn(COMPONENT, warnings[-1])
    trace.check(COMPONENT, True, "Document dates checked against treatment date.")

    # 3. Claimed amount vs bill totals.
    bill_totals = [d.total_amount for d in docs if d.total_amount is not None]
    if bill_totals:
        billed = sum(bill_totals)
        if abs(billed - claim.claimed_amount) > 1:
            warnings.append(
                f"Claimed amount ₹{claim.claimed_amount:,.0f} differs from the total "
                f"on the bill(s) ₹{billed:,.0f}."
            )
            trace.warn(COMPONENT, warnings[-1])
        else:
            trace.check(
                COMPONENT, True, f"Claimed amount matches bill total (₹{billed:,.0f})."
            )

    # 4. Prescription presence when the category requires one.
    if rules.requires_prescription:
        has_rx = any(d.doc_type.value == "PRESCRIPTION" for d in docs)
        trace.check(
            COMPONENT,
            has_rx,
            "Prescription present." if has_rx else "Category requires a prescription but none was extracted.",
        )
        if not has_rx:
            warnings.append("Required prescription is missing from extracted documents.")

    return warnings
