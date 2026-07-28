"""API-level tests: the HTTP boundary behaves as contracted.

Key contract: a REJECTED claim or a DOCUMENT_REJECTED early stop is a
business outcome, so it returns 200 — 4xx/5xx is reserved for malformed
requests and infrastructure failures.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
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

    # Stage order matches the pipeline; first event is the first node running.
    done_order = [s["stage"] for s in stages if s["status"] == "done"]
    assert done_order == [
        "verify_documents", "extract_documents", "cross_validate",
        "clinical_reasoning", "adjudicate", "fraud_check", "synthesize_decision",
    ]
    assert stages[0]["status"] == "running" and stages[0]["stage"] == "verify_documents"

    # Exactly one result, and it equals the sync endpoint's payload
    # (modulo volatile fields: claim_id, duration).
    assert len(results) == 1
    sync = client.post("/claims", json=DECIDED_PAYLOAD).json()
    streamed = results[0]["response"]
    for key in ("status", "member_message", "document_issues", "trace"):
        assert streamed[key] == sync[key]
    assert streamed["decision"]["decision"] == sync["decision"]["decision"] == "REJECTED"
    assert streamed["decision"]["approved_amount"] == sync["decision"]["approved_amount"]


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
    # Document problems stop the pipeline right after verification.
    assert done_stages == ["verify_documents"]
    result = next(e for e in events if e["type"] == "result")["response"]
    assert result["status"] == "DOCUMENT_REJECTED"
    assert result["document_issues"]
