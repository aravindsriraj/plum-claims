"""FastAPI application: the HTTP boundary.

Endpoints:
  POST /claims         — submit a claim, get back decision + full trace
  POST /claims/stream  — same, but streams per-stage progress as NDJSON,
                         ending with the identical response payload
  GET  /health         — liveness/readiness for Cloud Run

The app is intentionally thin: all behavior lives in the pipeline, so the
eval runner and the API exercise identical code paths.
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse
from app.llm.client import LlmClient
from app.policy.loader import load_policy
from app.service import ClaimService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the service once at startup. The LLM client is created only when
    a key is configured — without one, simulation-mode claims still work and
    vision-mode claims degrade gracefully via the resilience wrapper.
    CLAIMS_POLISH_MESSAGES=false disables the member-message prose pass
    (used by tests to stay fully deterministic)."""
    policy = load_policy()
    llm = LlmClient() if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") else None
    polish = os.getenv("CLAIMS_POLISH_MESSAGES", "true").lower() != "false"
    app.state.claim_service = ClaimService(policy, llm, polish_messages=polish)
    yield


app = FastAPI(title="Plum Claims Processing", version="1.0.0", lifespan=lifespan)

# The Next.js frontend calls this API from the browser; in production both
# services sit behind the same domain, but CORS stays permissive for local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/claims", response_model=ClaimResponse)
def submit_claim(claim: ClaimInput) -> ClaimResponse:
    """Process one claim end-to-end. Sync handler: the pipeline is CPU/IO
    bound on the LLM client, and FastAPI runs sync handlers in a threadpool."""
    return app.state.claim_service.process(claim)


@app.post("/claims/stream")
def submit_claim_stream(claim: ClaimInput) -> StreamingResponse:
    """Process one claim, streaming progress as newline-delimited JSON:
    one {"type":"stage",...} event per pipeline node, then a final
    {"type":"result","response":...} event with the same payload as /claims.
    X-Accel-Buffering: no — keep proxies from buffering the stream."""

    def lines():
        for event in app.state.claim_service.process_stream(claim):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": app.state.claim_service is not None,
    }
