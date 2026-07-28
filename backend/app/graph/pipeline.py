"""The claims pipeline as a LangGraph StateGraph.

Graph topology:

    verify_documents ──issues?──▶ END (DOCUMENT_REJECTED)
          │ no issues
    extract_documents
          │
    cross_validate        (warnings only, never stops)
          │
    adjudicate            (deterministic rules)
          │
    fraud_check
          │
    synthesize_decision ──▶ END (DECIDED)

Every LLM-touching or parse-heavy node runs inside the resilience wrapper:
a component failure is recorded in the trace, a fallback keeps the pipeline
moving, and confidence drops accordingly (assignment requirement #6).

Fault injection: `claim.simulate_component_failure` forces the cross-
validation node to raise, exercising exactly this path (TC011).
"""

from langgraph.graph import END, StateGraph

from app.agents.clinical_agent import run_clinical_reasoning_agent
from app.agents.cross_validation import cross_validate
from app.agents.decision import synthesize
from app.agents.document_verification import verify_documents
from app.agents.extraction import extract_documents
from app.graph.state import ClaimState
from app.observability.confidence import compute_confidence
from app.observability.resilience import run_resilient
from app.rules.adjudication import adjudicate
from app.rules.fraud import assess_fraud


def verify_documents_node(state: ClaimState) -> dict:
    """Agent 1: classify uploads and check them against policy requirements."""
    trace = state["trace"]
    trace.info("Pipeline", f"Claim received: {state['claim'].claim_category.value}, "
                           f"₹{state['claim'].claimed_amount:,.0f}, "
                           f"{len(state['claim'].documents)} document(s).")

    def run():
        return verify_documents(
            category=state["claim"].claim_category,
            member_name=state["member_name"],
            documents=state["claim"].documents,
            policy=state["policy"],
            trace=trace,
            llm=state.get("llm"),
        )

    def fallback():
        # Cannot verify documents at all -> stop with an honest issue.
        from app.contracts.documents import DocumentIssue
        from app.contracts.enums import DocumentIssueCode

        return [], [
            DocumentIssue(
                code=DocumentIssueCode.UNREADABLE_DOCUMENT,
                message=(
                    "We could not process your uploaded documents due to a temporary "
                    "system issue. Please try uploading them again. Your claim has not "
                    "been rejected."
                ),
            )
        ], {}

    classified, issues, reads = run_resilient(
        "DocumentVerificationAgent", run, fallback, trace
    )
    return {
        "classified_documents": classified,
        "document_issues": issues,
        "llm_reads": reads,
    }


def extract_documents_node(state: ClaimState) -> dict:
    """Agent 2: extract structured data from each document (per-doc isolation)."""
    trace = state["trace"]
    extracted = []
    for doc in state["claim"].documents:
        result = run_resilient(
            "ExtractionAgent",
            lambda doc=doc: extract_documents(
                [doc], state["classified_documents"], trace,
                state["policy"], llm_reads=state.get("llm_reads"),
            ),
            lambda: [],
            trace,
            fallback_description=f"document {doc.file_id} excluded from processing",
        )
        extracted.extend(result)
    return {"extracted_documents": extracted}


def cross_validate_node(state: ClaimState) -> dict:
    """Agent 3: cross-document consistency. Warnings only, never fatal.

    This node is the designated fault-injection point: TC011 sets
    simulate_component_failure to force it to raise, and the resilience
    wrapper degrades gracefully.
    """
    trace = state["trace"]

    def run():
        if state["claim"].simulate_component_failure:
            raise RuntimeError("Simulated component failure (fault injection)")
        return cross_validate(
            state["claim"], state["member_name"], state["extracted_documents"],
            state["policy"], trace, llm=state.get("llm"),
        )

    warnings = run_resilient(
        "CrossValidationAgent",
        run,
        lambda: ["Cross-validation was skipped after a component failure."],
        trace,
        fallback_description="consistency checks skipped; decision made on extracted data only",
    )
    return {"cross_validation_warnings": warnings}


def clinical_reasoning_node(state: ClaimState) -> dict:
    """Agent 3b: Clinical Reasoning ReAct Sub-Agent invoking domain tools."""
    trace = state["trace"]
    assessment = run_resilient(
        "ClinicalReasoningAgent",
        lambda: run_clinical_reasoning_agent(
            docs=state["extracted_documents"],
            policy=state["policy"],
            trace=trace,
            llm=state.get("llm"),
        ),
        lambda: None,
        trace,
        fallback_description="clinical reasoning agent skipped; relying on deterministic adjudication",
    )
    return {"clinical_assessment": assessment}


def adjudicate_node(state: ClaimState) -> dict:
    """Component 4: deterministic policy adjudication. No LLM involved."""
    result = adjudicate(state["claim"], state["policy"], state["extracted_documents"], state["trace"])
    return {"adjudication": result}


def fraud_check_node(state: ClaimState) -> dict:
    """Agent 5: fraud/velocity signals. Deterministic thresholds from policy."""
    trace = state["trace"]
    assessment = assess_fraud(
        member_id=state["claim"].member_id,
        treatment_date=state["claim"].treatment_date,
        claimed_amount=state["claim"].claimed_amount,
        claims_history=state["claim"].claims_history,
        thresholds=state["policy"].fraud_thresholds,
    )
    for signal in assessment.signals:
        trace.warn("FraudAgent", f"{signal.code}: {signal.description}")
    if not assessment.signals:
        trace.check("FraudAgent", True, "No fraud signals detected.")
    trace.info(
        "FraudAgent",
        f"Fraud score {assessment.fraud_score:.2f}; "
        f"manual review {'REQUIRED' if assessment.requires_manual_review else 'not required'}.",
    )
    return {"fraud": assessment}


def synthesize_decision_node(state: ClaimState) -> dict:
    """Agent 6: final decision + computed confidence."""
    trace = state["trace"]
    confidence = compute_confidence(
        state["extracted_documents"], trace.failures
    )
    trace.info(
        "DecisionSynthesizer",
        f"Confidence computed: {confidence:.2f} "
        f"(extraction quality x component-failure penalties).",
    )
    decision = synthesize(
        claimed_amount=state["claim"].claimed_amount,
        adjudication=state["adjudication"],
        fraud=state["fraud"],
        confidence=confidence,
        failures=trace.failures,
        cross_validation_warnings=state.get("cross_validation_warnings", []),
        trace=trace,
    )
    return {"decision": decision}


def _route_after_verification(state: ClaimState) -> str:
    """Early-stop edge: document problems end the run before any decision."""
    return "stop" if state["document_issues"] else "continue"


def build_graph() -> StateGraph:
    """Compile the pipeline. The returned graph is stateless per invocation —
    all per-claim data lives in ClaimState."""
    graph = StateGraph(ClaimState)

    graph.add_node("verify_documents", verify_documents_node)
    graph.add_node("extract_documents", extract_documents_node)
    graph.add_node("cross_validate", cross_validate_node)
    graph.add_node("clinical_reasoning", clinical_reasoning_node)
    graph.add_node("adjudicate", adjudicate_node)
    graph.add_node("fraud_check", fraud_check_node)
    graph.add_node("synthesize_decision", synthesize_decision_node)

    graph.set_entry_point("verify_documents")
    graph.add_conditional_edges(
        "verify_documents",
        _route_after_verification,
        {"stop": END, "continue": "extract_documents"},
    )
    graph.add_edge("extract_documents", "cross_validate")
    graph.add_edge("cross_validate", "clinical_reasoning")
    graph.add_edge("clinical_reasoning", "adjudicate")
    graph.add_edge("adjudicate", "fraud_check")
    graph.add_edge("fraud_check", "synthesize_decision")
    graph.add_edge("synthesize_decision", END)

    return graph.compile()
