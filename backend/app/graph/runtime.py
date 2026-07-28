"""Per-claim runtime context that must NOT live in checkpointed graph state.

LangGraph's MemorySaver/PostgresSaver serializes state. Policy, the LLM
client, TraceRecorder, and raw upload bytes are process-local — store them
here, keyed by claim_id (thread_id). Keeping base64 out of graph state also
keeps LangSmith spans small and readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.inputs import ClaimInput, DocumentInput
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

_REGISTRY: dict[str, "ClaimRuntime"] = {}


@dataclass
class DocumentBlob:
    content_base64: str
    mime_type: str | None = None


@dataclass
class ClaimRuntime:
    policy: Policy
    llm: LlmClient | None
    trace: TraceRecorder
    document_blobs: dict[str, DocumentBlob] = field(default_factory=dict)

    def hydrate_document(self, doc: DocumentInput) -> DocumentInput:
        """Reattach upload bytes for vision read (graph state stores metadata only)."""
        blob = self.document_blobs.get(doc.file_id)
        if blob is None:
            return doc
        return doc.model_copy(
            update={
                "file_content_base64": blob.content_base64,
                "mime_type": blob.mime_type or doc.mime_type,
            }
        )


def stash_document_bytes(claim: ClaimInput) -> tuple[ClaimInput, dict[str, DocumentBlob]]:
    """Move base64 off the claim object so it never enters LangGraph/LangSmith state."""
    blobs: dict[str, DocumentBlob] = {}
    docs: list[DocumentInput] = []
    for doc in claim.documents:
        if doc.file_content_base64:
            blobs[doc.file_id] = DocumentBlob(doc.file_content_base64, doc.mime_type)
            docs.append(doc.model_copy(update={"file_content_base64": None}))
        else:
            docs.append(doc)
    return claim.model_copy(update={"documents": docs}), blobs


def register_runtime(claim_id: str, runtime: ClaimRuntime) -> None:
    _REGISTRY[claim_id] = runtime


def get_runtime(claim_id: str) -> ClaimRuntime:
    try:
        return _REGISTRY[claim_id]
    except KeyError as exc:
        raise RuntimeError(
            f"No runtime registered for claim {claim_id}. "
            "ClaimService must register_runtime before invoking the graph."
        ) from exc


def clear_runtime(claim_id: str) -> None:
    _REGISTRY.pop(claim_id, None)
