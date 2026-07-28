"""LangSmith observability setup and helpers.

Configures tracing env vars, builds LangGraph RunnableConfigs with claim
metadata, and annotates the parent ProcessClaim run with the final decision.

Without LANGSMITH_API_KEY / LANGCHAIN_API_KEY this module is a no-op beyond
returning plain configs — unit tests and evals stay offline.
"""

from __future__ import annotations

import os
from typing import Any

from langsmith import get_current_run_tree, traceable

from app.contracts.inputs import ClaimInput
from app.contracts.responses import ClaimResponse


def configure_langsmith() -> None:
    """Export standard LangSmith / LangChain environment variables."""
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        return

    endpoint = (
        os.getenv("LANGSMITH_ENDPOINT")
        or os.getenv("LANGCHAIN_ENDPOINT")
        or "https://api.smith.langchain.com"
    )
    project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "plum-claims"

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project


def claim_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Strip bulky/PII-heavy fields (base64 bytes) from ProcessClaim inputs."""
    claim = inputs.get("claim")
    if claim is None:
        return {
            k: v
            for k, v in inputs.items()
            if k not in {"self", "on_stage", "on_interrupt"}
        }
    return sanitize_claim_for_trace(claim)


def sanitize_claim_for_trace(claim: ClaimInput) -> dict[str, Any]:
    return {
        "member_id": claim.member_id,
        "policy_id": claim.policy_id,
        "claim_category": claim.claim_category.value,
        "treatment_date": claim.treatment_date.isoformat(),
        "claimed_amount": claim.claimed_amount,
        "hospital_name": claim.hospital_name,
        "pre_auth_reference": claim.pre_auth_reference,
        "documents": [
            {
                "file_id": d.file_id,
                "file_name": d.file_name,
                "has_image": bool(d.file_content_base64),
                "simulated": d.actual_type is not None or d.quality is not None,
            }
            for d in claim.documents
        ],
    }


def claim_trace_outputs(outputs: Any) -> Any:
    """Compact ClaimResponse for the parent run outputs panel."""
    if isinstance(outputs, ClaimResponse):
        return summarize_response(outputs)
    return outputs


def summarize_response(response: ClaimResponse) -> dict[str, Any]:
    decision = response.decision
    return {
        "claim_id": response.claim_id,
        "status": response.status.value,
        "decision": decision.decision.value if decision else None,
        "approved_amount": decision.approved_amount if decision else None,
        "claimed_amount": decision.claimed_amount if decision else None,
        "document_issue_codes": [i.code.value for i in response.document_issues],
        "duration_ms": response.processing.duration_ms,
        "llm_calls": response.processing.llm_calls,
        "degraded": response.processing.degraded,
        "trace_events": len(response.trace),
    }


def graph_config(
    claim_id: str,
    *,
    mode: str,
    claim: ClaimInput | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LangGraph config: checkpointer thread + LangSmith tags/metadata."""
    metadata: dict[str, Any] = {"claim_id": claim_id, "mode": mode}
    tags = ["plum-claims", mode, claim_id]
    if claim is not None:
        metadata.update(
            {
                "member_id": claim.member_id,
                "policy_id": claim.policy_id,
                "claim_category": claim.claim_category.value,
                "claimed_amount": claim.claimed_amount,
                "document_count": len(claim.documents),
            }
        )
        tags.append(claim.claim_category.value)
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "configurable": {"thread_id": claim_id},
        "run_name": f"{mode}:{claim_id}",
        "tags": tags,
        "metadata": metadata,
    }


def annotate_claim_run(response: ClaimResponse) -> None:
    """Stamp final decision onto the current ProcessClaim parent run."""
    tree = get_current_run_tree()
    if tree is None:
        return
    summary = summarize_response(response)
    tree.add_outputs(summary)
    tree.add_metadata(
        {
            "claim_id": response.claim_id,
            "status": response.status.value,
            "decision": summary["decision"],
            "approved_amount": summary["approved_amount"],
            "duration_ms": summary["duration_ms"],
            "llm_calls": summary["llm_calls"],
            "degraded": summary["degraded"],
        }
    )
    if summary["decision"]:
        tree.add_tags([summary["decision"], response.status.value])
    else:
        tree.add_tags([response.status.value])


__all__ = [
    "annotate_claim_run",
    "claim_trace_inputs",
    "claim_trace_outputs",
    "configure_langsmith",
    "get_current_run_tree",
    "graph_config",
    "sanitize_claim_for_trace",
    "summarize_response",
    "traceable",
]
