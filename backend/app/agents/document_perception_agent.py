"""DocumentPerceptionAgent: tool-calling agent for one uploaded document.

True agent (`create_agent`): chooses tools to read a document. Efficiency rail —
`vision_read_document` may run at most once. Without an LLM (evals), falls back
to the deterministic simulation/metadata path (no agent loop).

Never decides coverage or money — perception only.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agents.tool_safety import run_missing_required_tools
from app.judgment.document_verification import LlmDocumentRead, read_document
from app.judgment.extraction import extract_one_document
from app.contracts.documents import ClassifiedDocument, ExtractedDocument
from app.contracts.enums import DocumentQuality, DocumentType, ExtractionMethod
from app.contracts.inputs import ClaimInput, DocumentInput
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

COMPONENT = "DocumentPerceptionAgent"

SYSTEM_PROMPT = """You are a document perception specialist for health insurance claims.
Your job is to read ONE medical document into structured fields.

Rules:
- If the document is a real image upload, call vision_read_document exactly once.
- If the document is simulation/eval metadata (no image), call apply_simulation_metadata.
- Then call finalize_extraction to build the structured ExtractedDocument.
- Call validate_extraction to confirm required fields before finishing.
- Never invent policy decisions, payouts, or waiting-period outcomes.
- Prefer precision; empty fields beat guesses.
"""


class DocumentPerceptionResult(BaseModel):
    summary: str = Field(default="Document perception completed.")
    used_vision: bool = False
    used_simulation: bool = False


def _deterministic_perceive(
    doc: DocumentInput,
    claim: ClaimInput,
    policy: Policy,
    llm: LlmClient | None,
    trace: TraceRecorder,
) -> tuple[ClassifiedDocument, ExtractedDocument | None]:
    """Eval / no-agent path: same behavior as the pre-agent worker."""
    classified, llm_read = read_document(doc, llm, policy, claim.claim_category)
    trace.record(
        COMPONENT,
        "EXTRACTION",
        "PASS",
        f"{doc.file_name or doc.file_id}: read as {classified.detected_type.value} "
        f"(quality {classified.quality.value}, confidence {classified.detection_confidence:.2f}, "
        f"via {classified.method.value}).",
        classified.model_dump(mode="json"),
    )
    extracted = extract_one_document(doc, classified, policy, trace, llm_read=llm_read)
    return classified, extracted


def run_document_perception_agent(
    doc: DocumentInput,
    claim: ClaimInput,
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> tuple[ClassifiedDocument, ExtractedDocument | None]:
    """Perceive one document. Returns (classified, extracted|None)."""
    # Evals and offline mode: no planner LLM — keep deterministic & fast.
    if llm is None:
        trace.skipped(
            COMPONENT,
            "No LLM — DocumentPerceptionAgent using deterministic read/extract path.",
        )
        return _deterministic_perceive(doc, claim, policy, llm, trace)

    store: dict[str, Any] = {
        "classified": None,
        "llm_read": None,
        "extracted": None,
        "vision_calls": 0,
        "tools_called": set(),
    }

    @tool
    def vision_read_document() -> str:
        """Read the uploaded image once with vision (classify + extract fields). At most once."""
        store["tools_called"].add("vision_read_document")
        if not doc.file_content_base64:
            return "ERROR: No image bytes on this document. Use apply_simulation_metadata instead."
        if store["vision_calls"] >= 1:
            return "Vision already called once for this document — do not call again."
        classified, llm_read = read_document(doc, llm, policy, claim.claim_category)
        store["classified"] = classified
        store["llm_read"] = llm_read
        store["vision_calls"] += 1
        return (
            f"OK: type={classified.detected_type.value}, quality={classified.quality.value}, "
            f"confidence={classified.detection_confidence:.2f}, "
            f"patient={classified.patient_name_on_doc or '(none)'}."
        )

    @tool
    def apply_simulation_metadata() -> str:
        """Use simulation/eval metadata (actual_type, quality, content) when there is no image."""
        store["tools_called"].add("apply_simulation_metadata")
        if doc.file_content_base64:
            return (
                "WARN: Image bytes are present. Prefer vision_read_document for real uploads. "
                "Simulation metadata ignored."
            )
        classified, llm_read = read_document(doc, llm, policy, claim.claim_category)
        store["classified"] = classified
        store["llm_read"] = llm_read
        return (
            f"OK: simulation type={classified.detected_type.value}, "
            f"quality={classified.quality.value}."
        )

    @tool
    def finalize_extraction() -> str:
        """Build the ExtractedDocument from the vision/simulation read."""
        store["tools_called"].add("finalize_extraction")
        classified = store["classified"]
        if classified is None:
            return "ERROR: Call vision_read_document or apply_simulation_metadata first."
        extracted = extract_one_document(
            doc, classified, policy, trace, llm_read=store["llm_read"]
        )
        store["extracted"] = extracted
        return (
            f"OK: extracted via {extracted.method.value}, "
            f"confidence={extracted.overall_confidence:.2f}, "
            f"line_items={len(extracted.line_items)}."
        )

    @tool
    def validate_extraction() -> str:
        """Sanity-check the extracted document before finishing."""
        store["tools_called"].add("validate_extraction")
        extracted = store["extracted"]
        classified = store["classified"]
        if extracted is None:
            return "ERROR: Call finalize_extraction first."
        problems: list[str] = []
        if classified and classified.detected_type == DocumentType.UNKNOWN:
            problems.append("detected_type is UNKNOWN")
        if classified and classified.quality == DocumentQuality.UNREADABLE:
            problems.append("quality is UNREADABLE")
        if not problems:
            return "OK: extraction looks usable."
        return "WARN: " + "; ".join(problems)

    agent = create_agent(
        model=llm._chat,
        tools=[
            vision_read_document,
            apply_simulation_metadata,
            finalize_extraction,
            validate_extraction,
        ],
        system_prompt=SYSTEM_PROMPT,
        response_format=DocumentPerceptionResult,
        name="document_perception_agent",
    )

    mode_hint = (
        "This document HAS image bytes — use vision_read_document."
        if doc.file_content_base64
        else "This document is simulation/metadata only — use apply_simulation_metadata."
    )
    raw = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Perceive document file_id={doc.file_id}, "
                        f"file_name={doc.file_name or '(none)'}, "
                        f"claim_category={claim.claim_category.value}.\n{mode_hint}"
                    ),
                }
            ]
        },
        config={
            "run_name": "document_perception_agent",
            "tags": ["document", "agent", "perception"],
            "metadata": {"file_id": doc.file_id},
            "recursion_limit": 12,
        },
    )

    structured = raw.get("structured_response")
    if isinstance(structured, dict):
        structured = DocumentPerceptionResult.model_validate(structured)

    # Safety rails: if the agent skipped steps, finish deterministically.
    if store["classified"] is None:
        trace.warn(COMPONENT, "Agent did not read the document — falling back to deterministic path.")
        return _deterministic_perceive(doc, claim, policy, llm, trace)

    # classified is guaranteed set here (early return above) — safe to finalize.
    run_missing_required_tools(
        ("finalize_extraction", "validate_extraction"),
        store["tools_called"],
        [vision_read_document, apply_simulation_metadata, finalize_extraction, validate_extraction],
        trace,
        COMPONENT,
    )

    classified: ClassifiedDocument = store["classified"]
    trace.record(
        COMPONENT,
        "EXTRACTION",
        "PASS",
        f"{doc.file_name or doc.file_id}: perceived as {classified.detected_type.value} "
        f"(quality {classified.quality.value}, via agent tools "
        f"{sorted(store['tools_called'])}"
        + (
            f"; {structured.summary}"
            if isinstance(structured, DocumentPerceptionResult)
            else ""
        )
        + ").",
        classified.model_dump(mode="json"),
    )
    return classified, store["extracted"]
