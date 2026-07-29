"""CrossValidationAgent: thin wrapper around ConsistencyAgent.

Kept for backward-compatible imports. Soft consistency checks now run via the
tool-calling ConsistencyAgent (`run_consistency_agent`).
"""

from app.agents.consistency_agent import (
    DATE_TOLERANCE_DAYS,
    LlmClinicalVerdict,
    LlmNameVerdict,
    run_consistency_agent,
)
from app.contracts.documents import ExtractedDocument
from app.contracts.inputs import ClaimInput
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

__all__ = [
    "DATE_TOLERANCE_DAYS",
    "LlmClinicalVerdict",
    "LlmNameVerdict",
    "cross_validate",
]


def cross_validate(
    claim: ClaimInput,
    member_name: str,
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> list[str]:
    """Run consistency checks (delegates to ConsistencyAgent)."""
    return run_consistency_agent(claim, member_name, docs, policy, trace, llm=llm)
