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
