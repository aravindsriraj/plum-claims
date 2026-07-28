"""ExtractionAgent: turns each verified document into structured, tagged data.

Two modes, selected per document:
  - PROVIDED_CONTENT: the caller supplied extracted content (eval harness).
    It is normalized through the same Pydantic schema as vision output, so
    downstream components cannot tell the difference. Clinical text is tagged
    by the deterministic matcher (evals stay LLM-free).
  - VISION_LLM: the DocumentVerificationAgent's single vision read already
    extracted this document's fields and semantic tags — this agent shapes
    that read into an ExtractedDocument (no second LLM call), validates the
    model's tags against the policy vocabulary, and merges them with the
    deterministic matcher's tags (union; disagreements flagged).

This agent NEVER judges coverage. It reports what the document says and how
that content maps onto the policy vocabulary — adjudication decides the rest.
"""

from app.agents.document_verification import LlmDocumentRead
from app.contracts.documents import (
    ClassifiedDocument,
    DocumentTags,
    ExtractedDocument,
    LineItem,
    PolicyTag,
)
from app.contracts.enums import DocumentQuality, ExtractionMethod
from app.contracts.inputs import DocumentInput
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.tagging import (
    merge_tags,
    tag_deterministic,
    tag_line_items,
    validate_llm_tags,
)
from app.util import parse_iso_date

COMPONENT = "ExtractionAgent"


def _from_provided_content(
    doc: DocumentInput, classified: ClassifiedDocument, policy: Policy
) -> ExtractedDocument:
    """Normalize caller-supplied content (eval/simulation mode) and tag it
    with the deterministic matcher — evals exercise the production fallback."""
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
        # Canonical key is provider_name; hospital_name kept as a deprecated alias.
        provider_name=content.get("provider_name") or content.get("hospital_name"),
        document_date=parse_iso_date(content.get("date")),
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
    extracted.tags = tag_deterministic(
        policy, extracted.diagnosis, extracted.treatment, *extracted.tests_ordered
    )
    tag_line_items(policy, extracted.line_items)
    return extracted


def _from_llm_read(
    doc: DocumentInput,
    classified: ClassifiedDocument,
    read: LlmDocumentRead,
    policy: Policy,
    trace: TraceRecorder,
) -> ExtractedDocument:
    """Shape the verification agent's raw vision read into an
    ExtractedDocument, then validate + merge its semantic tags.

    The model's tags are perception: they are whitelist-checked against the
    policy vocabulary (hallucinated entries dropped + flagged), then merged
    with the deterministic matcher's tags — union, disagreements traced.
    """
    extracted = ExtractedDocument(
        file_id=doc.file_id,
        doc_type=classified.detected_type,
        method=ExtractionMethod.VISION_LLM,
        patient_name=read.patient_name or classified.patient_name_on_doc,
        doctor_name=read.doctor_name,
        doctor_registration=read.doctor_registration,
        provider_name=read.provider_name,
        document_date=parse_iso_date(read.document_date),
        diagnosis=read.diagnosis,
        treatment=read.treatment,
        medicines=read.medicines,
        tests_ordered=read.tests_ordered,
        line_items=read.line_items,
        total_amount=read.total_amount,
        overall_confidence=read.overall_confidence,
        unreadable_fields=read.unreadable_fields,
    )

    llm_tags = DocumentTags(
        conditions=read.matched_conditions,
        exclusions=[
            PolicyTag(entry=t.entry, matched_text=t.evidence or read.diagnosis or "", via="llm")
            for t in read.matched_exclusions
        ],
    )
    clean_llm_tags, warnings = validate_llm_tags(llm_tags, policy)
    det_tags = tag_deterministic(
        policy, extracted.diagnosis, extracted.treatment, *extracted.tests_ordered
    )
    merged = merge_tags(clean_llm_tags, det_tags, file_id=doc.file_id)
    extracted.tags = merged.tags
    warnings.extend(merged.warnings)
    warnings.extend(tag_line_items(policy, extracted.line_items))
    for warning in warnings:
        trace.warn(COMPONENT, warning)
    return extracted


def extract_one_document(
    doc: DocumentInput,
    classified: ClassifiedDocument,
    policy: Policy,
    trace: TraceRecorder,
    llm_read: LlmDocumentRead | None = None,
) -> ExtractedDocument:
    """Extract structured data from a single document (used by Send workers)."""
    if doc.file_content_base64:
        if llm_read is None:
            raise RuntimeError(
                f"Vision read for {doc.file_id} missing — verification "
                f"must read every uploaded document exactly once"
            )
        extracted = _from_llm_read(doc, classified, llm_read, policy, trace)
    elif doc.content is not None:
        extracted = _from_provided_content(doc, classified, policy)
    else:
        extracted = ExtractedDocument(
            file_id=doc.file_id,
            doc_type=classified.detected_type,
            method=ExtractionMethod.METADATA,
            patient_name=classified.patient_name_on_doc,
            overall_confidence=0.5,
            tags=DocumentTags(),
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
    return extracted


def extract_documents(
    documents: list[DocumentInput],
    classified: list[ClassifiedDocument],
    trace: TraceRecorder,
    policy: Policy,
    llm_reads: dict[str, LlmDocumentRead] | None = None,
) -> list[ExtractedDocument]:
    """Extract structured data from every document.

    Per-document failures are isolated by the caller (graph node wraps this in
    run_resilient per document); a document that fails extraction is simply
    absent from the returned list, and the failure is in the trace.
    """
    by_id = {c.file_id: c for c in classified}
    reads = llm_reads or {}
    results: list[ExtractedDocument] = []

    for doc in documents:
        results.append(
            extract_one_document(
                doc, by_id[doc.file_id], policy, trace, llm_read=reads.get(doc.file_id)
            )
        )

    return results
