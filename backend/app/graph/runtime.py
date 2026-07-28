"""Per-claim runtime context that must NOT live in checkpointed graph state.

LangGraph's MemorySaver/PostgresSaver serializes state. Policy, the LLM
client, and TraceRecorder are process-local objects — store them here,
keyed by claim_id (thread_id).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

_REGISTRY: dict[str, "ClaimRuntime"] = {}


@dataclass
class ClaimRuntime:
    policy: Policy
    llm: LlmClient | None
    trace: TraceRecorder


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
