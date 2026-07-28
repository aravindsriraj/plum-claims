"""FastAPI application: the HTTP boundary.

Endpoints:
  POST /claims                — submit a claim
  POST /claims/stream         — NDJSON stage + optional interrupt + result
  POST /claims/{id}/resume    — HITL approve/reject
  GET  /health
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse
from app.contracts.resume import ResumeClaimRequest
from app.llm.client import LlmClient
from app.observability.langsmith import configure_langsmith
from app.policy.loader import load_policy
from app.service import ClaimService

configure_langsmith()


@asynccontextmanager
async def lifespan(app: FastAPI):
    policy = load_policy()
    llm = LlmClient() if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") else None
    polish = os.getenv("CLAIMS_POLISH_MESSAGES", "true").lower() != "false"
    app.state.claim_service = ClaimService(policy, llm, polish_messages=polish)
    yield


app = FastAPI(title="Plum Claims Processing", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/claims", response_model=ClaimResponse)
def submit_claim(claim: ClaimInput) -> ClaimResponse:
    return app.state.claim_service.process(claim)


@app.post("/claims/stream")
def submit_claim_stream(claim: ClaimInput) -> StreamingResponse:
    def lines():
        for event in app.state.claim_service.process_stream(claim):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post("/claims/{claim_id}/resume", response_model=ClaimResponse)
def resume_claim(claim_id: str, body: ResumeClaimRequest) -> ClaimResponse:
    try:
        return app.state.claim_service.resume(claim_id, body.action, body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    svc = app.state.claim_service
    return {
        "status": "ok",
        "llm_configured": svc is not None and svc._llm is not None,
        "hitl_enabled": bool(getattr(svc, "_hitl", False)),
    }
