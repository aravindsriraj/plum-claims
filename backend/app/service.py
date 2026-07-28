"""ClaimService: the application boundary between HTTP and the pipeline.

Owns per-claim orchestration: build the trace, resolve the member, invoke
the graph, and assemble the ClaimResponse. Kept separate from the graph so
the graph stays transport-agnostic (the eval runner uses it directly too).

Two consumption modes over the SAME pipeline run:
  - process():        invoke to completion, return the response.
  - process_stream(): yield per-stage progress events as the graph advances,
                      then the identical response as the final event.
"""

import time
import uuid
from collections.abc import Iterator

from app.agents.explanation import build_explanation
from app.agents.member_message import polish_member_message
from app.contracts.enums import ClaimStatus
from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse, ProcessingMeta
from app.graph.pipeline import build_graph
from app.llm.client import LlmClient
from app.observability.langsmith import configure_langsmith, traceable
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

configure_langsmith()

# Pipeline node -> member-facing stage label. Order is the graph's order.
STAGES: list[tuple[str, str]] = [
    ("verify_documents", "Verifying documents"),
    ("extract_documents", "Reading documents"),
    ("cross_validate", "Cross-checking details"),
    ("adjudicate", "Applying policy rules"),
    ("fraud_check", "Fraud screening"),
    ("synthesize_decision", "Finalizing decision"),
]


class ClaimService:
    """Stateless service — safe to share one instance across requests."""

    def __init__(
        self,
        policy: Policy,
        llm: LlmClient | None = None,
        polish_messages: bool = True,
    ) -> None:
        self._policy = policy
        self._llm = llm
        # Member-message polish (LLM prose pass) — off in evals/tests so the
        # deterministic template is what's asserted.
        self._polish = polish_messages
        self._graph = build_graph()

    def _initial_state(self, claim: ClaimInput, trace: TraceRecorder) -> dict:
        member = self._policy.find_member(claim.member_id)
        return {
            "claim": claim,
            "policy": self._policy,
            "trace": trace,
            "llm": self._llm,
            "member_name": member.name if member else claim.member_id,
        }

    @traceable(name="ProcessClaim", run_type="chain")
    def process(self, claim: ClaimInput) -> ClaimResponse:
        started = time.perf_counter()
        trace = TraceRecorder()
        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
        llm_calls_before = self._llm.call_count if self._llm else 0
        final_state = self._graph.invoke(self._initial_state(claim, trace))
        return self._assemble(claim_id, trace, final_state, started, llm_calls_before)

    def process_stream(self, claim: ClaimInput) -> Iterator[dict]:
        """Yield NDJSON-ready dicts: one 'stage' event per pipeline node as it
        completes (with the next node marked running), then a final 'result'
        event carrying the same ClaimResponse process() would return.

        Stage summaries quote the real trace lines the node just produced —
        progress is the pipeline narrating itself, never a simulation.
        """
        started = time.perf_counter()
        trace = TraceRecorder()
        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
        llm_calls_before = self._llm.call_count if self._llm else 0
        labels = dict(STAGES)
        order = [node for node, _ in STAGES]

        yield {"type": "stage", "stage": order[0], "label": labels[order[0]], "status": "running"}

        final_state: dict = {}
        trace_cursor = 0
        for update in self._graph.stream(
            self._initial_state(claim, trace), stream_mode="updates"
        ):
            (node, delta), = update.items()
            final_state.update(delta)

            # The trace lines this node appended become its progress summary.
            new_events = trace.events[trace_cursor:]
            trace_cursor = len(trace.events)
            summary = new_events[-1].summary if new_events else ""

            yield {
                "type": "stage",
                "stage": node,
                "label": labels.get(node, node),
                "status": "done",
                "summary": summary,
            }
            idx = order.index(node)
            if idx + 1 < len(order):
                nxt = order[idx + 1]
                yield {"type": "stage", "stage": nxt, "label": labels[nxt], "status": "running"}

        yield {
            "type": "result",
            "response": self._assemble(
                claim_id, trace, final_state, started, llm_calls_before
            ).model_dump(mode="json"),
        }

    def _assemble(
        self,
        claim_id: str,
        trace: TraceRecorder,
        final_state: dict,
        started: float,
        llm_calls_before: int,
    ) -> ClaimResponse:
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
            # Optional prose polish: the LLM rewrites style only, validated to
            # preserve every figure; any failure keeps the template.
            if self._polish and self._llm is not None:
                try:
                    member_message = polish_member_message(member_message, self._llm, trace)
                except Exception as exc:  # noqa: BLE001 — prose pass must never break a decision
                    trace.warn(
                        "MemberMessagePolisher",
                        f"Polish failed ({type(exc).__name__}); template message kept.",
                    )

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
                # call_count is cumulative on the shared client — report the delta.
                llm_calls=(self._llm.call_count - llm_calls_before) if self._llm else 0,
            ),
        )
        response.explanation = build_explanation(response)
        return response
