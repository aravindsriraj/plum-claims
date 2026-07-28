"""CrossValidationAgent: consistency checks ACROSS documents and claim.

Nothing here can reject a claim outright — inconsistencies reduce confidence
and can route to manual review via soft signals. Hard stops for identity
problems already happened in DocumentVerificationAgent.

Checks:
  1. Patient name on documents vs member roster name. Exact matching is
     deterministic; when names differ, an LLM second opinion (perception —
     "is 'R. Kumar' the same person as 'Rajesh Kumar'?") can CLEAR the
     warning, never create one. No LLM / LLM disagrees -> warning stands.
  2. Document dates vs the claimed treatment date.
  3. Bill total vs the claimed amount.
  4. Provider on the claim form vs provider on the documents.
  5. Prescription requirement (category rules) — is a prescription among the
     extracted docs when the category mandates one?
"""

from pydantic import BaseModel, Field

from app.contracts.documents import ExtractedDocument
from app.contracts.inputs import ClaimInput
from app.llm.client import LlmClient
from app.llm.prompts import NAME_RECONCILIATION_PROMPT
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.textnorm import normalize

COMPONENT = "CrossValidationAgent"

# How far apart a document date and the claimed treatment date may be before
# we flag it. Small gaps happen (report issued next day); big ones are odd.
DATE_TOLERANCE_DAYS = 3


class LlmNameVerdict(BaseModel):
    """Structured output for name reconciliation: are these the same person?"""

    same_person: bool
    rationale: str = Field(default="")


def _reconcile_names(
    member_name: str, mismatched: list[str], llm: LlmClient | None
) -> list[str]:
    """LLM second opinion on name mismatches (perception, warning-level only).

    Returns the subset of names the LLM could NOT reconcile with the member.
    Without an LLM, every mismatch stands (deterministic behavior unchanged).
    """
    if llm is None:
        return mismatched
    unreconciled: list[str] = []
    for name in mismatched:
        verdict = llm.structured(
            LlmNameVerdict,
            NAME_RECONCILIATION_PROMPT.format(member_name=member_name, doc_name=name),
        )
        if not verdict.same_person:
            unreconciled.append(name)
    return unreconciled


def cross_validate(
    claim: ClaimInput,
    member_name: str,
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
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
            unreconciled = _reconcile_names(member_name, mismatched, llm)
            if unreconciled:
                warnings.append(
                    f"Extracted patient name(s) {unreconciled} do not match member "
                    f"'{member_name}'."
                )
                trace.warn(COMPONENT, warnings[-1])
            else:
                trace.check(
                    COMPONENT, True,
                    f"Name variant(s) {mismatched} reconciled with member "
                    f"'{member_name}' (LLM second opinion).",
                )
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

    # 4. Provider consistency: the hospital named on the claim form must match
    # the provider on the documents — a disagreement here is a classic
    # network-discount abuse vector (claiming a network hospital on the form
    # while the bill is from a non-network provider).
    doc_providers = [d.provider_name for d in docs if d.provider_name]
    if claim.hospital_name and doc_providers:
        form_provider = normalize(claim.hospital_name)
        if not any(
            form_provider in normalize(p) or normalize(p) in form_provider
            for p in doc_providers
        ):
            warnings.append(
                f"Provider mismatch: the claim form says '{claim.hospital_name}' but "
                f"the document(s) are from "
                + ", ".join(f"'{p}'" for p in doc_providers)
                + "."
            )
            trace.warn(COMPONENT, warnings[-1])

    # 5. Prescription presence when the category requires one.
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
