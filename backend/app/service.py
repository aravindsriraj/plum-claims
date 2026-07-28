"""ClaimService: the application boundary between HTTP and the pipeline.

Owns per-claim orchestration: build the trace, resolve the member, invoke
the graph, and assemble the ClaimResponse. Kept separate from the graph so
the graph stays transport-agnostic (the eval runner uses it directly too).
"""

import time
import uuid

from app.agents.explanation import build_explanation
from app.contracts.enums import ClaimStatus
from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse, ProcessingMeta
from app.graph.pipeline import build_graph
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy


class ClaimService:
    """Stateless service — safe to share one instance across requests."""

    def __init__(self, policy: Policy, llm: LlmClient | None = None) -> None:
        self._policy = policy
        self._llm = llm
        self._graph = build_graph()

    def process(self, claim: ClaimInput) -> ClaimResponse:
        started = time.perf_counter()
        trace = TraceRecorder()
        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

        member = self._policy.find_member(claim.member_id)
        member_name = member.name if member else claim.member_id

        final_state = self._graph.invoke(
            {
                "claim": claim,
                "policy": self._policy,
                "trace": trace,
                "llm": self._llm,
                "member_name": member_name,
            }
        )

        issues = final_state.get("document_issues", [])
        decision = final_state.get("decision")
        status = ClaimStatus.DOCUMENT_REJECTED if issues else ClaimStatus.DECIDED

        if status == ClaimStatus.DOCUMENT_REJECTED:
            member_message = (
                "We couldn't process your claim yet — please fix the following and "
                "resubmit: " + " ".join(i.message for i in issues)
            )
        else:
            member_message = {
                "APPROVED": f"Your claim has been approved. ₹{decision.approved_amount:,.0f} "
                f"of ₹{decision.claimed_amount:,.0f} will be paid.",
                "PARTIAL": f"Your claim was partially approved: ₹{decision.approved_amount:,.0f} "
                f"of ₹{decision.claimed_amount:,.0f}. See the breakdown for details.",
                "REJECTED": "Your claim was rejected. " + " ".join(decision.reasons),
                "MANUAL_REVIEW": "Your claim needs a manual review by our team. "
                "We'll follow up shortly — no action needed from you right now.",
            }[decision.decision.value]

        response = ClaimResponse(
            claim_id=claim_id,
            status=status,
            member_message=member_message,
            document_issues=issues,
            decision=decision,
            trace=trace.events,
            processing=ProcessingMeta(
                duration_ms=int((time.perf_counter() - started) * 1000),
                degraded=bool(trace.failures),
                llm_calls=self._llm.call_count if self._llm else 0,
            ),
        )
        response.explanation = build_explanation(response)
        return response
