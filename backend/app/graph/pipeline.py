"""The claims pipeline as a LangGraph Claims Orchestrator.

    START ──Send──▶ document_worker × N   ← DocumentPerceptionAgent (tool-calling)
                        │
              verify_document_set ──issues?──▶ END (DOCUMENT_REJECTED)
                        │
              clinical_tagging     ← ClinicalAgent (tool-calling)
                        │
              cross_validate       ← ConsistencyAgent (tool-calling)
                        │
              adjudicate → fraud_check → synthesize → human_review_gate → END

Non-serializable objects (policy, llm, trace, upload bytes) live in
app.graph.runtime, keyed by claim_id — required for checkpointer-backed HITL.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send, interrupt
from typing_extensions import TypedDict

from app.agents.clinical_agent import run_clinical_tagging_agent
from app.agents.consistency_agent import run_consistency_agent
from app.agents.decision import synthesize
from app.agents.document_perception_agent import run_document_perception_agent
from app.agents.document_verification import evaluate_document_set
from app.contracts.decision import AdjudicationResult, ClaimDecision, FraudAssessment
from app.contracts.documents import ClassifiedDocument, DocumentIssue, ExtractedDocument
from app.contracts.enums import Decision, DocumentQuality, DocumentType, ExtractionMethod
from app.contracts.inputs import ClaimInput, DocumentInput
from app.graph.runtime import get_runtime
from app.observability.confidence import compute_confidence
from app.observability.resilience import run_resilient
from app.rules.adjudication import adjudicate
from app.rules.fraud import assess_fraud


class ClaimGraphState(TypedDict, total=False):
    claim: ClaimInput
    claim_id: str
    member_name: str
    hitl_enabled: bool

    # Fan-out accumulators
    classified_documents: Annotated[list[ClassifiedDocument], operator.add]
    extracted_documents: Annotated[list[ExtractedDocument], operator.add]

    # Post fan-in (overwrite, not reduced)
    documents: list[ExtractedDocument]
    document_issues: list[DocumentIssue]
    document: DocumentInput  # worker-local

    cross_validation_warnings: list[str]
    adjudication: AdjudicationResult
    fraud: FraudAssessment
    decision: ClaimDecision


def _docs(state: ClaimGraphState) -> list[ExtractedDocument]:
    return state.get("documents") or state.get("extracted_documents") or []


def fan_out_documents(state: ClaimGraphState) -> list[Send]:
    """Map: one parallel worker per upload. Also logs claim receipt."""
    rt = get_runtime(state["claim_id"])
    claim = state["claim"]
    rt.trace.info(
        "Pipeline",
        f"Claim received: {claim.claim_category.value}, "
        f"₹{claim.claimed_amount:,.0f}, {len(claim.documents)} document(s).",
    )
    return [
        Send(
            "document_worker",
            {
                "document": doc,
                "claim": claim,
                "claim_id": state["claim_id"],
            },
        )
        for doc in claim.documents
    ]


def document_worker_node(state: ClaimGraphState) -> dict:
    """Worker: DocumentPerceptionAgent (tool-calling) for one upload."""
    claim = state["claim"]
    rt = get_runtime(state["claim_id"])
    doc = rt.hydrate_document(state["document"])

    def perceive():
        return run_document_perception_agent(doc, claim, rt.policy, rt.trace, llm=rt.llm)

    def perceive_fallback():
        classified = ClassifiedDocument(
            file_id=doc.file_id,
            file_name=doc.file_name,
            detected_type=doc.actual_type or DocumentType.UNKNOWN,
            detection_confidence=0.0,
            quality=DocumentQuality.UNREADABLE,
            patient_name_on_doc=doc.patient_name_on_doc,
            method=ExtractionMethod.METADATA,
        )
        return classified, None

    classified, extracted = run_resilient(
        "DocumentPerceptionAgent",
        perceive,
        perceive_fallback,
        rt.trace,
        fallback_description=f"document {doc.file_id} marked unreadable after perception failure",
    )
    updates: dict[str, Any] = {"classified_documents": [classified]}
    if extracted is not None:
        updates["extracted_documents"] = [extracted]
    return updates


def verify_document_set_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])
    issues = evaluate_document_set(
        category=state["claim"].claim_category,
        member_name=state["member_name"],
        classified=state.get("classified_documents") or [],
        policy=rt.policy,
        trace=rt.trace,
    )
    return {"document_issues": issues}


def clinical_tagging_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])
    docs = state.get("extracted_documents") or []
    enriched = run_resilient(
        "ClinicalTaggingAgent",
        lambda: run_clinical_tagging_agent(docs, rt.policy, rt.trace, rt.llm),
        lambda: docs,
        rt.trace,
        fallback_description="clinical tagging skipped; deterministic tags retained",
    )
    return {"documents": enriched}


def cross_validate_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])

    def run():
        if state["claim"].simulate_component_failure:
            raise RuntimeError("Simulated component failure (fault injection)")
        return run_consistency_agent(
            state["claim"], state["member_name"], _docs(state), rt.policy, rt.trace, llm=rt.llm
        )

    warnings = run_resilient(
        "ConsistencyAgent",
        run,
        lambda: ["Cross-validation was skipped after a component failure."],
        rt.trace,
        fallback_description="consistency checks skipped; decision made on extracted data only",
    )
    return {"cross_validation_warnings": warnings}


def adjudicate_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])
    return {"adjudication": adjudicate(state["claim"], rt.policy, _docs(state), rt.trace, llm=rt.llm)}


def fraud_check_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])
    assessment = assess_fraud(
        member_id=state["claim"].member_id,
        treatment_date=state["claim"].treatment_date,
        claimed_amount=state["claim"].claimed_amount,
        claims_history=state["claim"].claims_history,
        thresholds=rt.policy.fraud_thresholds,
    )
    for signal in assessment.signals:
        rt.trace.warn("FraudAgent", f"{signal.code}: {signal.description}")
    if not assessment.signals:
        rt.trace.check("FraudAgent", True, "No fraud signals detected.")
    rt.trace.info(
        "FraudAgent",
        f"Fraud score {assessment.fraud_score:.2f}; "
        f"manual review {'REQUIRED' if assessment.requires_manual_review else 'not required'}.",
    )
    return {"fraud": assessment}


def synthesize_decision_node(state: ClaimGraphState) -> dict:
    rt = get_runtime(state["claim_id"])
    confidence = compute_confidence(_docs(state), rt.trace.failures)
    rt.trace.info(
        "DecisionSynthesizer",
        f"Confidence computed: {confidence:.2f} "
        f"(extraction quality x component-failure penalties).",
    )
    return {
        "decision": synthesize(
            claimed_amount=state["claim"].claimed_amount,
            adjudication=state["adjudication"],
            fraud=state["fraud"],
            confidence=confidence,
            failures=rt.trace.failures,
            cross_validation_warnings=state.get("cross_validation_warnings", []),
            trace=rt.trace,
        )
    }


def _apply_ops_resume(
    decision: ClaimDecision,
    adjudication: AdjudicationResult,
    resume: Any,
    trace,
) -> ClaimDecision:
    action = (resume or {}).get("action", "reject") if isinstance(resume, dict) else "reject"
    note = (resume or {}).get("note") if isinstance(resume, dict) else None

    if action == "approve":
        approved = float(adjudication.approved_amount or 0.0)
        updated = decision.model_copy(
            update={
                "decision": Decision.APPROVED,
                "approved_amount": approved,
                "reasons": [
                    "Manually approved by operations after review.",
                    *([note] if note else []),
                    f"Approved ₹{approved:,.0f} of ₹{decision.claimed_amount:,.0f}.",
                ],
            }
        )
        trace.info("HumanReviewGate", f"Ops APPROVED — paying ₹{approved:,.0f}.")
        return updated

    updated = decision.model_copy(
        update={
            "decision": Decision.REJECTED,
            "approved_amount": 0.0,
            "rejection_reasons": [*decision.rejection_reasons, "MANUAL_REJECTED"],
            "reasons": [
                "Manually rejected by operations after review.",
                *([note] if note else []),
            ],
        }
    )
    trace.info("HumanReviewGate", "Ops REJECTED the claim.")
    return updated


def human_review_gate_node(state: ClaimGraphState) -> dict:
    """Pause for ops when MANUAL_REVIEW and HITL is enabled."""
    rt = get_runtime(state["claim_id"])
    decision = state.get("decision")
    if (
        not state.get("hitl_enabled")
        or decision is None
        or decision.decision != Decision.MANUAL_REVIEW
    ):
        return {}

    payload = {
        "claim_id": state["claim_id"],
        "draft_decision": decision.decision.value,
        "claimed_amount": decision.claimed_amount,
        "adjudicated_amount": state["adjudication"].approved_amount,
        "reasons": decision.reasons,
        "fraud_signals": [s.model_dump() for s in decision.fraud_signals],
        "message": (
            "This claim was flagged for manual review. "
            "Approve to pay the adjudicated amount, or reject the claim."
        ),
    }
    rt.trace.info("HumanReviewGate", "Pausing for human-in-the-loop review (MANUAL_REVIEW).", payload)
    resume = interrupt(payload)
    return {
        "decision": _apply_ops_resume(decision, state["adjudication"], resume, rt.trace)
    }


def _route_after_verification(state: ClaimGraphState) -> list[str]:
    return [END] if state.get("document_issues") else ["clinical_tagging", "cross_validate"]


def build_graph(checkpointer=None):
    graph = StateGraph(ClaimGraphState)

    retry_policy = RetryPolicy(max_attempts=2)

    graph.add_node("document_worker", document_worker_node, retry_policy=retry_policy)
    graph.add_node("verify_document_set", verify_document_set_node)
    graph.add_node("clinical_tagging", clinical_tagging_node, retry_policy=retry_policy)
    graph.add_node("cross_validate", cross_validate_node, retry_policy=retry_policy)
    graph.add_node("adjudicate", adjudicate_node)
    graph.add_node("fraud_check", fraud_check_node)
    graph.add_node("synthesize_decision", synthesize_decision_node)
    graph.add_node("human_review_gate", human_review_gate_node)

    graph.add_conditional_edges(START, fan_out_documents, ["document_worker"])
    graph.add_edge("document_worker", "verify_document_set")
    graph.add_conditional_edges(
        "verify_document_set",
        _route_after_verification,
        ["clinical_tagging", "cross_validate", END],
    )
    graph.add_edge("clinical_tagging", "adjudicate")
    graph.add_edge("cross_validate", "adjudicate")
    graph.add_edge("adjudicate", "fraud_check")
    graph.add_edge("fraud_check", "synthesize_decision")
    graph.add_edge("synthesize_decision", "human_review_gate")
    graph.add_edge("human_review_gate", END)

    return graph.compile(checkpointer=checkpointer)
