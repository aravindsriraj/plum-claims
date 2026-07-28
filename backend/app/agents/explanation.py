"""ExplanationBuilder: renders the trace into an ops-readable narrative.

Deterministic template rendering — NOT an LLM summary. An LLM paraphrase
could drift from what actually happened; the whole point of the explanation
is fidelity to the trace.
"""

from app.contracts.enums import ClaimStatus, TraceStatus
from app.contracts.responses import ClaimResponse


def build_explanation(response: ClaimResponse) -> str:
    """Produce a plain-English walkthrough of what the pipeline did."""
    lines: list[str] = [f"Claim {response.claim_id}: {response.status.value}.", ""]

    if response.status == ClaimStatus.DOCUMENT_REJECTED:
        lines.append("Processing stopped at document verification:")
        for issue in response.document_issues:
            lines.append(f"  [{issue.code.value}] {issue.message}")
        lines.append("")
        lines.append("No claim decision was made.")

    if response.decision:
        d = response.decision
        lines.append(
            f"Decision: {d.decision.value} — approved ₹{d.approved_amount:,.0f} "
            f"of ₹{d.claimed_amount:,.0f} (confidence {d.confidence_score:.2f})."
        )
        for reason in d.reasons:
            lines.append(f"  {reason}")
        if d.adjustments:
            lines.append("Financial breakdown:")
            for adj in d.adjustments:
                lines.append(
                    f"  {adj.kind.value}: ₹{adj.amount_before:,.0f} -> ₹{adj.amount_after:,.0f} ({adj.note})"
                )
        if d.degraded:
            lines.append("WARNING: processing was degraded (see component failures).")

    lines.append("")
    lines.append("Pipeline trace:")
    for event in response.trace:
        marker = {
            TraceStatus.PASS: "PASS",
            TraceStatus.FAIL: "FAIL",
            TraceStatus.WARN: "WARN",
            TraceStatus.SKIPPED: "SKIP",
        }[event.status]
        lines.append(f"  {event.sequence:>3}. [{marker}] {event.component}: {event.summary}")

    return "\n".join(lines)
