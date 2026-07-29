"""ClaimService: HTTP/eval boundary around the LangGraph pipeline."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.explanation import build_explanation
from app.agents.member_message import polish_member_message
from app.contracts.enums import ClaimStatus, Decision
from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse, ProcessingMeta
from app.graph.pipeline import build_graph
from app.graph.runtime import ClaimRuntime, clear_runtime, register_runtime, stash_document_bytes
from app.llm.client import LlmClient
from app.observability.langsmith import (
    annotate_claim_run,
    claim_stream_outputs,
    claim_trace_inputs,
    claim_trace_outputs,
    graph_config,
    traceable,
)
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

STAGES: list[tuple[str, str]] = [
    ("document_worker", "Document perception"),
    ("verify_document_set", "Verifying document set"),
    ("clinical_tagging", "Clinical policy tagging"),
    ("cross_validate", "Consistency checks"),
    ("adjudicate", "Applying policy rules"),
    ("fraud_check", "Fraud screening"),
    ("synthesize_decision", "Finalizing decision"),
    ("human_review_gate", "Human review"),
]

_MEMBER_TEMPLATES = {
    Decision.APPROVED: (
        "Your claim has been approved. ₹{approved:,.0f} of ₹{claimed:,.0f} will be paid."
    ),
    Decision.PARTIAL: (
        "Your claim was partially approved: ₹{approved:,.0f} of ₹{claimed:,.0f}. "
        "See the breakdown for details."
    ),
    Decision.REJECTED: "Your claim was rejected. {reasons}",
    Decision.MANUAL_REVIEW: (
        "Your claim needs a manual review by our team. "
        "We'll follow up shortly — no action needed from you right now."
    ),
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes"}


class ClaimService:
    def __init__(
        self,
        policy: Policy,
        llm: LlmClient | None = None,
        polish_messages: bool = True,
        hitl_enabled: bool | None = None,
    ) -> None:
        self._policy = policy
        self._llm = llm
        self._polish = polish_messages
        self._hitl = _env_flag("CLAIMS_HITL") if hitl_enabled is None else hitl_enabled
        self._graph = build_graph(checkpointer=MemorySaver())
        self._traces: dict[str, TraceRecorder] = {}
        self._started: dict[str, float] = {}
        self._llm_baseline: dict[str, int] = {}

    def _config(
        self,
        claim_id: str,
        *,
        mode: str,
        claim: ClaimInput | None = None,
        extra_metadata: dict | None = None,
    ) -> dict:
        return graph_config(
            claim_id, mode=mode, claim=claim, extra_metadata=extra_metadata
        )

    def _prepare(self, claim: ClaimInput) -> tuple[str, TraceRecorder, float, int, dict]:
        started = time.perf_counter()
        trace = TraceRecorder()
        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
        llm_before = self._llm.call_count if self._llm else 0
        self._traces[claim_id] = trace
        self._started[claim_id] = started
        self._llm_baseline[claim_id] = llm_before
        # Keep upload bytes in runtime — not in checkpointed / LangSmith graph state.
        claim_for_graph, blobs = stash_document_bytes(claim)
        register_runtime(
            claim_id,
            ClaimRuntime(
                policy=self._policy,
                llm=self._llm,
                trace=trace,
                document_blobs=blobs,
            ),
        )
        member = self._policy.find_member(claim.member_id)
        return claim_id, trace, started, llm_before, {
            "claim": claim_for_graph,
            "claim_id": claim_id,
            "member_name": member.name if member else claim.member_id,
            "hitl_enabled": self._hitl,
        }

    def _interrupted(self, claim_id: str) -> tuple[bool, Any]:
        if not self._hitl:
            return False, None
        snapshot = self._graph.get_state(self._config(claim_id, mode="inspect"))
        if not snapshot or not snapshot.tasks:
            return False, None
        for task in snapshot.tasks:
            interrupts = getattr(task, "interrupts", None) or ()
            if interrupts:
                return True, interrupts[0].value
        return False, None

    @traceable(
        name="ProcessClaim",
        run_type="chain",
        process_inputs=claim_trace_inputs,
        process_outputs=claim_trace_outputs,
    )
    def process(self, claim: ClaimInput) -> ClaimResponse:
        claim_id, trace, started, llm_before, initial = self._prepare(claim)
        result = self._graph.invoke(
            initial, self._config(claim_id, mode="sync", claim=claim)
        )
        awaiting, _ = self._interrupted(claim_id)
        if not awaiting:
            awaiting = bool(result.get("__interrupt__"))
        return self._assemble(claim_id, trace, result, started, llm_before, awaiting=awaiting)

    @traceable(
        name="ProcessClaim",
        run_type="chain",
        process_inputs=claim_trace_inputs,
        process_outputs=claim_stream_outputs,
    )
    def process_stream(self, claim: ClaimInput) -> Iterator[dict]:
        claim_id, trace, started, llm_before, initial = self._prepare(claim)
        labels = dict(STAGES)
        first = STAGES[0][0]
        yield {"type": "stage", "stage": first, "label": labels[first], "status": "running"}

        trace_cursor = 0
        for update in self._graph.stream(
            initial,
            self._config(claim_id, mode="stream", claim=claim),
            stream_mode="updates",
        ):
            if not isinstance(update, dict) or not update:
                continue
            node, _delta = next(iter(update.items()))
            if node == "__interrupt__":
                continue
            new_events = trace.events[trace_cursor:]
            trace_cursor = len(trace.events)
            yield {
                "type": "stage",
                "stage": node,
                "label": labels.get(node, node),
                "status": "done",
                "summary": new_events[-1].summary if new_events else "",
            }

        snapshot = self._graph.get_state(self._config(claim_id, mode="stream", claim=claim))
        values = dict(snapshot.values) if snapshot else {}
        awaiting, interrupt_payload = self._interrupted(claim_id)
        if awaiting:
            yield {"type": "interrupt", "claim_id": claim_id, "payload": interrupt_payload}
        response = self._assemble(
            claim_id, trace, values, started, llm_before, awaiting=awaiting
        )
        yield {
            "type": "result",
            "response": response.model_dump(mode="json"),
        }

    @traceable(
        name="ResumeClaim",
        run_type="chain",
        process_inputs=claim_trace_inputs,
        process_outputs=claim_trace_outputs,
    )
    def resume(self, claim_id: str, action: str, note: str | None = None) -> ClaimResponse:
        trace = self._traces.get(claim_id)
        if trace is None:
            raise KeyError(f"Unknown or expired claim_id: {claim_id}")
        started = self._started.get(claim_id, time.perf_counter())
        llm_before = self._llm_baseline.get(claim_id, 0)
        result = self._graph.invoke(
            Command(resume={"action": action, "note": note}),
            self._config(
                claim_id,
                mode="resume",
                extra_metadata={"resume_action": action},
            ),
        )
        awaiting, _ = self._interrupted(claim_id)
        return self._assemble(claim_id, trace, result, started, llm_before, awaiting=awaiting)

    def _member_message(self, status: ClaimStatus, issues, decision, trace: TraceRecorder) -> str:
        if status == ClaimStatus.DOCUMENT_REJECTED:
            return (
                "We couldn't process your claim yet — please fix the following and "
                "resubmit: " + " ".join(i.message for i in issues)
            )
        if status == ClaimStatus.AWAITING_HUMAN_REVIEW:
            return _MEMBER_TEMPLATES[Decision.MANUAL_REVIEW]

        template = _MEMBER_TEMPLATES[decision.decision]
        message = template.format(
            approved=decision.approved_amount,
            claimed=decision.claimed_amount,
            reasons=" ".join(decision.reasons),
        )
        if self._polish and self._llm is not None:
            try:
                return polish_member_message(message, self._llm, trace)
            except Exception as exc:  # noqa: BLE001
                trace.warn(
                    "MemberMessagePolisher",
                    f"Polish failed ({type(exc).__name__}); template message kept.",
                )
        return message

    def _assemble(
        self,
        claim_id: str,
        trace: TraceRecorder,
        final_state: dict,
        started: float,
        llm_calls_before: int,
        *,
        awaiting: bool = False,
    ) -> ClaimResponse:
        issues = final_state.get("document_issues") or []
        decision = final_state.get("decision")

        if issues:
            status = ClaimStatus.DOCUMENT_REJECTED
        elif awaiting:
            status = ClaimStatus.AWAITING_HUMAN_REVIEW
        else:
            status = ClaimStatus.DECIDED

        response = ClaimResponse(
            claim_id=claim_id,
            status=status,
            member_message=self._member_message(status, issues, decision, trace),
            document_issues=issues,
            decision=decision,
            trace=trace.events,
            processing=ProcessingMeta(
                duration_ms=int((time.perf_counter() - started) * 1000),
                degraded=bool(trace.failures),
                llm_calls=(self._llm.call_count - llm_calls_before) if self._llm else 0,
            ),
        )
        response.explanation = build_explanation(response)
        annotate_claim_run(response)
        if not awaiting:
            clear_runtime(claim_id)
        return response
