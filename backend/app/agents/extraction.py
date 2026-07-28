"""ExtractionAgent: turns each verified document into structured data.

Two modes, selected per document:
  - PROVIDED_CONTENT: the caller supplied extracted content (eval harness).
    It is normalized through the same Pydantic schema as vision output, so
    downstream components cannot tell the difference.
  - VISION_LLM: a vision model reads the actual file. Messy inputs (handwriting,
    stamps, blur) are handled by instructing the model to mark illegible fields
    as unreadable rather than guess — degraded confidence, not wrong data.

This agent NEVER judges coverage. It only reports what the document says.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.contracts.documents import ClassifiedDocument, ExtractedDocument, LineItem
from app.contracts.enums import DocumentQuality, DocumentType, ExtractionMethod
from app.contracts.inputs import DocumentInput
from app.llm.client import LlmClient
from app.llm.prompts import DOCUMENT_EXTRACTION_PROMPT
from app.observability.trace import TraceRecorder

COMPONENT = "ExtractionAgent"


class LlmExtraction(BaseModel):
    """Structured output schema for vision extraction.

    Deliberately mirrors ExtractedDocument so the two modes converge.
    """

    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    provider_name: str | None = None
    document_date: str | None = Field(default=None, description="ISO YYYY-MM-DD")
    diagnosis: str | None = None
    treatment: str | None = None
    medicines: list[str] = Field(default_factory=list)
    tests_ordered: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    total_amount: float | None = None
    unreadable_fields: list[str] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.8, ge=0, le=1)


def _parse_date(value: Any) -> date | None:
    """Best-effort ISO date parse; anything else becomes None + unreadable."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _from_provided_content(doc: DocumentInput, classified: ClassifiedDocument) -> ExtractedDocument:
    """Normalize caller-supplied content (eval/simulation mode)."""
    content = doc.content or {}
    line_items = [
        LineItem(description=str(li.get("description", "")), amount=float(li.get("amount", 0)))
        for li in content.get("line_items", [])
    ]
    extracted = ExtractedDocument(
        file_id=doc.file_id,
        doc_type=classified.detected_type,
        method=ExtractionMethod.PROVIDED_CONTENT,
        patient_name=content.get("patient_name") or classified.patient_name_on_doc,
        doctor_name=content.get("doctor_name"),
        doctor_registration=content.get("doctor_registration"),
        provider_name=content.get("hospital_name") or content.get("provider_name"),
        document_date=_parse_date(content.get("date")),
        diagnosis=content.get("diagnosis"),
        treatment=content.get("treatment"),
        medicines=list(content.get("medicines", [])),
        tests_ordered=list(content.get("tests_ordered", [])),
        line_items=line_items,
        total_amount=(
            float(content["total"]) if content.get("total") is not None else None
        ),
        # Provided content is ground truth for evals: full confidence, but a
        # LOW-quality document still erodes it — the scan itself was degraded.
        overall_confidence=1.0 if classified.quality == DocumentQuality.GOOD else 0.7,
        raw_content=dict(content),
    )
    return extracted


def extract_documents(
    documents: list[DocumentInput],
    classified: list[ClassifiedDocument],
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> list[ExtractedDocument]:
    """Extract structured data from every document.

    Per-document failures are isolated by the caller (graph node wraps this in
    run_resilient per document); a document that fails extraction is simply
    absent from the returned list, and the failure is in the trace.
    """
    by_id = {c.file_id: c for c in classified}
    results: list[ExtractedDocument] = []

    for doc in documents:
        cd = by_id[doc.file_id]
        if doc.file_content_base64:
            if llm is None:
                raise RuntimeError("Vision extraction requires an LLM client")
            out = llm.structured(
                LlmExtraction,
                DOCUMENT_EXTRACTION_PROMPT.format(doc_type=cd.detected_type.value),
                image_base64=doc.file_content_base64,
                mime_type=doc.mime_type or "image/jpeg",
            )
            extracted = ExtractedDocument(
                file_id=doc.file_id,
                doc_type=cd.detected_type,
                method=ExtractionMethod.VISION_LLM,
                patient_name=out.patient_name or cd.patient_name_on_doc,
                doctor_name=out.doctor_name,
                doctor_registration=out.doctor_registration,
                provider_name=out.provider_name,
                document_date=_parse_date(out.document_date),
                diagnosis=out.diagnosis,
                treatment=out.treatment,
                medicines=out.medicines,
                tests_ordered=out.tests_ordered,
                line_items=out.line_items,
                total_amount=out.total_amount,
                overall_confidence=out.overall_confidence,
                unreadable_fields=out.unreadable_fields,
            )
        elif doc.content is not None:
            extracted = _from_provided_content(doc, cd)
        else:
            # Metadata-only document (eval cases that stop before extraction):
            # an empty shell so downstream stages see the file existed.
            extracted = ExtractedDocument(
                file_id=doc.file_id,
                doc_type=cd.detected_type,
                method=ExtractionMethod.METADATA,
                patient_name=cd.patient_name_on_doc,
                overall_confidence=0.5,
            )

        trace.record(
            COMPONENT,
            "EXTRACTION",
            "PASS",
            f"{doc.file_id}: extracted via {extracted.method.value} "
            f"(confidence {extracted.overall_confidence:.2f}"
            + (
                f", unreadable: {extracted.unreadable_fields}"
                if extracted.unreadable_fields
                else ""
            )
            + ")",
            extracted.model_dump(mode="json"),
        )
        results.append(extracted)

    return results
