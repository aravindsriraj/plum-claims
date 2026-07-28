"""DocumentVerificationAgent: the pipeline's first gate.

Reads every upload ONCE with the vision model (classification + extraction +
policy tagging in a single structured call), judges the submission against
the policy's document requirements for the claim category, and stashes the
raw read for the ExtractionAgent to build from — 2N -> N LLM calls per claim.
Any problem produces a specific, member-actionable DocumentIssue — never a
generic error — and the pipeline stops before any claim decision
(assignment requirement #2).

Reading has two modes:
  - Real uploads (file_content_base64 present): one vision call per document.
  - Simulation metadata present (actual_type/quality): used directly, no LLM.
    This keeps eval cases deterministic and targets this agent's decision
    logic rather than OCR quality.
"""

from pydantic import BaseModel, Field

from app.contracts.documents import ClassifiedDocument, DocumentIssue, LineItem
from app.contracts.enums import (
    ClaimCategory,
    DocumentIssueCode,
    DocumentQuality,
    DocumentType,
    ExtractionMethod,
)
from app.contracts.inputs import DocumentInput
from app.llm.client import LlmClient
from app.llm.prompts import DOCUMENT_READ_PROMPT
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.textnorm import normalize

COMPONENT = "DocumentVerificationAgent"


class LlmExclusionTag(BaseModel):
    """An exclusion the model believes applies. Validated against the policy
    vocabulary downstream — never trusted blindly."""

    entry: str = Field(..., description="Verbatim policy exclusion entry")
    evidence: str = Field(default="", description="Document text indicating it")


class LlmDocumentRead(BaseModel):
    """Single vision read of one document: classification + extraction +
    policy-vocabulary tags in one structured output."""

    # --- classification half ---
    doc_type: DocumentType
    quality: DocumentQuality
    classification_confidence: float = Field(ge=0, le=1)
    # --- extraction half ---
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
    # --- policy tagging half (perception only; judged downstream) ---
    matched_conditions: list[str] = Field(default_factory=list)
    matched_exclusions: list[LlmExclusionTag] = Field(default_factory=list)


def _vocabulary(policy: Policy, category: ClaimCategory) -> dict[str, str]:
    """The policy vocabulary injected into the read prompt."""
    rules = policy.category_rules(category)
    covered = rules.covered_procedures + rules.covered_items
    excluded = rules.excluded_procedures + rules.excluded_items
    hv_tests = rules.high_value_tests_requiring_pre_auth
    return {
        "category": category.value,
        "condition_keys": ", ".join(policy.specific_condition_waiting_days) or "(none)",
        "exclusion_entries": "\n".join(f"- {e}" for e in policy.excluded_conditions),
        "covered_procedures": ", ".join(covered) if covered else "(no list — judge by exclusion entries only)",
        "excluded_procedures": ", ".join(excluded) if excluded else "(none)",
        "high_value_tests": ", ".join(hv_tests) if hv_tests else "(none for this category)",
    }


def read_document(
    doc: DocumentInput, llm: LlmClient | None, policy: Policy, category: ClaimCategory
) -> tuple[ClassifiedDocument, LlmDocumentRead | None]:
    """Read one document: vision model for real uploads, metadata otherwise.

    Returns (classified_document, raw_llm_read). The raw read is None for
    simulation-mode documents. Raises if vision is needed but no LLM client
    is available — the caller wraps this in the resilience wrapper.
    """
    if doc.file_content_base64:
        if llm is None:
            raise RuntimeError("Vision read requires an LLM client")
        read = llm.structured(
            LlmDocumentRead,
            DOCUMENT_READ_PROMPT.format(**_vocabulary(policy, category)),
            image_base64=doc.file_content_base64,
            mime_type=doc.mime_type or "image/jpeg",
        )
        return ClassifiedDocument(
            file_id=doc.file_id,
            file_name=doc.file_name,
            detected_type=read.doc_type,
            detection_confidence=read.classification_confidence,
            quality=read.quality,
            patient_name_on_doc=read.patient_name,
            method=ExtractionMethod.VISION_LLM,
        ), read

    # Simulation path: ground-truth metadata describes the document.
    return ClassifiedDocument(
        file_id=doc.file_id,
        file_name=doc.file_name,
        detected_type=doc.actual_type or DocumentType.UNKNOWN,
        detection_confidence=1.0 if doc.actual_type else 0.0,
        quality=doc.quality or DocumentQuality.GOOD,
        patient_name_on_doc=doc.patient_name_on_doc,
        method=ExtractionMethod.METADATA,
    ), None


def verify_documents(
    category: ClaimCategory,
    member_name: str,
    documents: list[DocumentInput],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> tuple[list[ClassifiedDocument], list[DocumentIssue], dict[str, LlmDocumentRead]]:
    """Read all uploads and validate the set against policy requirements.

    Returns (classified_documents, issues, llm_reads). A non-empty issues list
    means the pipeline must stop; the issues tell the member exactly what to
    fix. llm_reads carries the raw vision read per file_id for the
    ExtractionAgent (empty in simulation mode).
    """
    requirement = policy.document_requirement(category)
    issues: list[DocumentIssue] = []
    classified: list[ClassifiedDocument] = []
    reads: dict[str, LlmDocumentRead] = {}

    # Step 1: read each document (or read its simulation metadata).
    for doc in documents:
        cd, read = read_document(doc, llm, policy, category)
        classified.append(cd)
        if read is not None:
            reads[doc.file_id] = read
        trace.record(
            COMPONENT,
            "EXTRACTION",
            "PASS",
            f"{doc.file_name or doc.file_id}: read as {cd.detected_type.value} "
            f"(quality {cd.quality.value}, confidence {cd.detection_confidence:.2f}, "
            f"via {cd.method.value}).",
            cd.model_dump(mode="json"),
        )

    # Step 2: unreadable documents — ask for a re-upload of that specific file.
    for cd in classified:
        if cd.quality == DocumentQuality.UNREADABLE:
            doc_label = (
                cd.detected_type.value.replace("_", " ").lower()
                if cd.detected_type != DocumentType.UNKNOWN
                else "document"
            )
            issues.append(
                DocumentIssue(
                    code=DocumentIssueCode.UNREADABLE_DOCUMENT,
                    file_id=cd.file_id,
                    found=f"{cd.file_name or cd.file_id} ({cd.detected_type.value})",
                    expected=f"A clear, readable photo or scan of your {doc_label}",
                    message=(
                        f"We couldn't read your {doc_label} "
                        f"('{cd.file_name or cd.file_id}') — the image is too blurry or damaged. "
                        f"Please re-upload a clear photo of that same document. Your claim has "
                        f"NOT been rejected; it will continue once we can read this document."
                    ),
                )
            )
            trace.warn(COMPONENT, f"{cd.file_id}: document unreadable, re-upload requested.")

    # Step 3: required document types for this claim category.
    present_types = {cd.detected_type for cd in classified}
    for required_type in requirement.required:
        if required_type not in present_types:
            uploaded = ", ".join(
                f"'{cd.file_name or cd.file_id}' ({cd.detected_type.value})" for cd in classified
            )
            issues.append(
                DocumentIssue(
                    code=DocumentIssueCode.MISSING_DOCUMENT,
                    found=f"uploaded: {uploaded}",
                    expected=required_type.value,
                    message=(
                        f"Your {category.value.replace('_', ' ').lower()} claim requires a "
                        f"{required_type.value.replace('_', ' ').lower()}, but you uploaded "
                        f"{uploaded}. Please upload your "
                        f"{required_type.value.replace('_', ' ').lower()} to continue."
                    ),
                )
            )
            trace.warn(
                COMPONENT, f"Required document {required_type.value} is missing from the upload."
            )

    # Step 4: wrong document type uploaded in place of a required one.
    # Two flavors: a type this claim doesn't accept at all, or a SURPLUS
    # duplicate (e.g. a second prescription when a bill is what's missing).
    accepted_types = set(requirement.required) | set(requirement.optional)
    seen_types: set[DocumentType] = set()
    for cd in classified:
        # An unreadable document already has its own issue above; piling a
        # wrong-type complaint on top would be noise, not signal.
        if cd.quality == DocumentQuality.UNREADABLE:
            continue
        is_surplus_duplicate = cd.detected_type in seen_types
        seen_types.add(cd.detected_type)
        if cd.detected_type not in accepted_types or is_surplus_duplicate:
            missing = [t for t in requirement.required if t not in present_types]
            expected = (
                f"we still need your {missing[0].value.replace('_', ' ').lower()}"
                if missing
                else f"this claim only accepts: "
                + ", ".join(t.value for t in sorted(accepted_types, key=str))
            )
            issues.append(
                DocumentIssue(
                    code=DocumentIssueCode.WRONG_DOCUMENT_TYPE,
                    file_id=cd.file_id,
                    found=f"'{cd.file_name or cd.file_id}' is a {cd.detected_type.value}",
                    expected=expected,
                    message=(
                        f"'{cd.file_name or cd.file_id}' is a "
                        f"{cd.detected_type.value.replace('_', ' ').lower()}, but "
                        f"{expected}. Please upload the correct document."
                    ),
                )
            )
            trace.warn(
                COMPONENT,
                f"{cd.file_id}: {cd.detected_type.value} does not satisfy the requirements.",
            )

    # Step 5: patient identity — all documents must name the same patient,
    # and that patient must be the claiming member.
    named = [(cd.file_id, cd.file_name, cd.patient_name_on_doc) for cd in classified]
    named = [n for n in named if n[2]]
    distinct_names = {normalize(n[2]) for n in named}
    if len(distinct_names) > 1:
        per_doc = "; ".join(
            f"'{fname or fid}' belongs to {pname}" for fid, fname, pname in named
        )
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.PATIENT_MISMATCH,
                found=per_doc,
                expected=f"All documents must be for the same patient ({member_name})",
                message=(
                    f"Your documents appear to belong to different people: {per_doc}. "
                    f"Please upload documents for {member_name} only."
                ),
            )
        )
        trace.warn(COMPONENT, f"Patient mismatch across documents: {per_doc}.")
    elif distinct_names and normalize(member_name) not in distinct_names.pop():
        # Single patient on the docs, but not the claiming member.
        per_doc = "; ".join(
            f"'{fname or fid}' belongs to {pname}" for fid, fname, pname in named
        )
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.PATIENT_MISMATCH,
                found=per_doc,
                expected=f"Documents for {member_name}",
                message=(
                    f"These documents are not in your name: {per_doc}. "
                    f"Please upload documents issued to {member_name}."
                ),
            )
        )
        trace.warn(COMPONENT, f"Documents name a different patient than {member_name}.")

    if not issues:
        trace.info(
            COMPONENT,
            f"Document set satisfies {category.value} requirements "
            f"(required: {[t.value for t in requirement.required]}).",
        )
    return classified, issues, reads
