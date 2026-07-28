"""API-level tests: the HTTP boundary behaves as contracted.

Key contract: a REJECTED claim or a DOCUMENT_REJECTED early stop is a
business outcome, so it returns 200 — 4xx/5xx is reserved for malformed
requests and infrastructure failures.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy.loader import load_policy
from app.service import ClaimService


@pytest.fixture(scope="module")
def client():
    # Deterministic HTTP tests: no LLM, no HITL — mirrors eval mode.
    with TestClient(app) as c:
        app.state.claim_service = ClaimService(
            load_policy(), llm=None, polish_messages=False, hitl_enabled=False
        )
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_document_rejected_is_200_with_issues(client):
    payload = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "documents": [
            {"file_id": "F001", "actual_type": "PRESCRIPTION"},
            {"file_id": "F002", "actual_type": "PRESCRIPTION"},
        ],
    }
    resp = client.post("/claims", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DOCUMENT_REJECTED"
    assert body["decision"] is None
    assert body["document_issues"]
    # Trace is present even for early stops.
    assert len(body["trace"]) > 0


def test_decided_claim_returns_full_decision(client):
    payload = {
        "member_id": "EMP009",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-18",
        "claimed_amount": 8000,
        "documents": [
            {
                "file_id": "F023",
                "actual_type": "PRESCRIPTION",
                "content": {"diagnosis": "Morbid Obesity — BMI 37"},
            },
            {
                "file_id": "F024",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "line_items": [{"description": "Bariatric Consultation", "amount": 3000}],
                    "total": 8000,
                },
            },
        ],
    }
    resp = client.post("/claims", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DECIDED"
    assert body["decision"]["decision"] == "REJECTED"
    assert "EXCLUDED_CONDITION" in body["decision"]["rejection_reasons"]
    assert body["decision"]["confidence_score"] > 0.90
    assert body["explanation"]


def test_malformed_input_is_422(client):
    resp = client.post("/claims", json={"member_id": "EMP001"})
    assert resp.status_code == 422


# ---------------------------------------------------------------- streaming
DECIDED_PAYLOAD = {
    "member_id": "EMP009",
    "policy_id": "PLUM_GHI_2024",
    "claim_category": "CONSULTATION",
    "treatment_date": "2024-10-18",
    "claimed_amount": 8000,
    "documents": [
        {
            "file_id": "F023",
            "actual_type": "PRESCRIPTION",
            "content": {"diagnosis": "Morbid Obesity — BMI 37"},
        },
        {
            "file_id": "F024",
            "actual_type": "HOSPITAL_BILL",
            "content": {
                "line_items": [{"description": "Bariatric Consultation", "amount": 3000}],
                "total": 8000,
            },
        },
    ],
}


def test_stream_emits_stages_in_order_then_identical_result(client):
    import json

    resp = client.post("/claims/stream", json=DECIDED_PAYLOAD)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")

    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    stages = [e for e in events if e["type"] == "stage"]
    results = [e for e in events if e["type"] == "result"]

    done_order = [s["stage"] for s in stages if s["status"] == "done"]
    # Parallel workers may emit document_worker more than once; assert key milestones.
    assert done_order[0] == "document_worker"
    assert "document_worker" in done_order
    assert "verify_document_set" in done_order
    assert "clinical_tagging" in done_order
    assert "adjudicate" in done_order
    assert "fraud_check" in done_order
    assert done_order[-1] == "human_review_gate"
    assert stages[0]["status"] == "running" and stages[0]["stage"] == "document_worker"

    assert len(results) == 1
    sync = client.post("/claims", json=DECIDED_PAYLOAD).json()
    streamed = results[0]["response"]
    assert streamed["status"] == sync["status"]
    assert streamed["decision"]["decision"] == sync["decision"]["decision"] == "REJECTED"
    assert streamed["decision"]["approved_amount"] == sync["decision"]["approved_amount"]
    assert streamed["document_issues"] == sync["document_issues"]
    # Trace event order can vary slightly with parallel document workers.
    assert len(streamed["trace"]) == len(sync["trace"])


def test_stream_early_stop_ends_after_verification(client):
    import json

    payload = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "documents": [
            {"file_id": "F001", "actual_type": "PRESCRIPTION"},
            {"file_id": "F002", "actual_type": "PRESCRIPTION"},
        ],
    }
    resp = client.post("/claims/stream", json=payload)
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    done_stages = [e["stage"] for e in events if e["type"] == "stage" and e["status"] == "done"]
    assert "verify_document_set" in done_stages
    assert "adjudicate" not in done_stages
    assert done_stages[-1] == "verify_document_set"
    result = next(e for e in events if e["type"] == "result")["response"]
    assert result["status"] == "DOCUMENT_REJECTED"
    assert result["document_issues"]


def test_hitl_pause_and_resume_approve(client, monkeypatch):
    """With CLAIMS_HITL, MANUAL_REVIEW pauses; resume approve finalizes APPROVED."""
    from app.main import app
    from app.policy.loader import load_policy
    from app.service import ClaimService

    svc = ClaimService(load_policy(), llm=None, polish_messages=False, hitl_enabled=True)
    app.state.claim_service = svc

    payload = {
        "member_id": "EMP008",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-30",
        "claimed_amount": 4800,
        "claims_history": [
            {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "A"},
            {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "B"},
            {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "C"},
        ],
        "documents": [
            {
                "file_id": "F017",
                "actual_type": "PRESCRIPTION",
                "content": {"diagnosis": "Migraine", "doctor_name": "Dr. S. Khan"},
            },
            {
                "file_id": "F018",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "line_items": [{"description": "Consultation Fee", "amount": 4800}],
                    "total": 4800,
                },
            },
        ],
    }
    paused = client.post("/claims", json=payload).json()
    assert paused["status"] == "AWAITING_HUMAN_REVIEW"
    assert paused["decision"]["decision"] == "MANUAL_REVIEW"
    claim_id = paused["claim_id"]

    resumed = client.post(
        f"/claims/{claim_id}/resume", json={"action": "approve", "note": "Cleared by ops"}
    ).json()
    assert resumed["status"] == "DECIDED"
    assert resumed["decision"]["decision"] == "APPROVED"
    assert resumed["decision"]["approved_amount"] > 0
