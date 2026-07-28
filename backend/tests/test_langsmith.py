"""Unit tests for LangSmith helper sanitization (no network)."""

from datetime import date

from app.contracts.decision import ClaimDecision
from app.contracts.enums import ClaimCategory, ClaimStatus, Decision, DocumentType
from app.contracts.inputs import ClaimInput, DocumentInput
from app.contracts.responses import ClaimResponse, ProcessingMeta
from app.observability.langsmith import (
    claim_stream_outputs,
    claim_trace_inputs,
    graph_config,
    sanitize_claim_for_trace,
    summarize_response,
)


def test_sanitize_claim_strips_base64():
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="POL-TEST",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500,
        documents=[
            DocumentInput(
                file_id="F1",
                file_name="bill.jpg",
                file_content_base64="a" * 5000,
                actual_type=DocumentType.HOSPITAL_BILL,
            )
        ],
    )
    out = sanitize_claim_for_trace(claim)
    assert out["member_id"] == "EMP001"
    assert out["documents"][0]["has_image"] is True
    assert "file_content_base64" not in str(out)
    assert "aaaa" not in str(out)


def test_claim_trace_inputs_from_kwargs():
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="POL-TEST",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="F1", actual_type=DocumentType.HOSPITAL_BILL),
        ],
    )
    assert claim_trace_inputs({"self": object(), "claim": claim})["claimed_amount"] == 1500


def test_graph_config_includes_thread_and_tags():
    claim = ClaimInput(
        member_id="EMP001",
        policy_id="POL-TEST",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500,
        documents=[
            DocumentInput(file_id="F1", actual_type=DocumentType.HOSPITAL_BILL),
        ],
    )
    cfg = graph_config("CLM-ABC", mode="stream", claim=claim)
    assert cfg["configurable"]["thread_id"] == "CLM-ABC"
    assert "stream" in cfg["tags"]
    assert cfg["metadata"]["member_id"] == "EMP001"
    assert cfg["run_name"] == "ClaimsGraph"


def test_summarize_response():
    response = ClaimResponse(
        claim_id="CLM-1",
        status=ClaimStatus.DECIDED,
        member_message="ok",
        decision=ClaimDecision(
            decision=Decision.APPROVED,
            claimed_amount=1500,
            approved_amount=1350,
            confidence_score=0.9,
            reasons=["ok"],
        ),
        processing=ProcessingMeta(duration_ms=12, llm_calls=2, degraded=False),
    )
    summary = summarize_response(response)
    assert summary["decision"] == "APPROVED"
    assert summary["approved_amount"] == 1350
    assert summary["llm_calls"] == 2


def test_claim_stream_outputs_keeps_only_result_summary():
    yields = [
        {"type": "stage", "stage": "document_worker", "status": "running"},
        {"type": "stage", "stage": "document_worker", "status": "done"},
        {
            "type": "result",
            "response": {
                "claim_id": "CLM-1",
                "status": "DECIDED",
                "decision": {"decision": "APPROVED", "approved_amount": 1350, "claimed_amount": 1500},
                "document_issues": [],
                "processing": {"duration_ms": 10, "llm_calls": 2, "degraded": False},
            },
        },
    ]
    out = claim_stream_outputs(yields)
    assert out["claim_id"] == "CLM-1"
    assert out["decision"] == "APPROVED"
    assert out["stage_events"] == 2
    assert "output" not in out
