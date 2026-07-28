"""Observability contracts: the trace.

The trace is a first-class artifact. Every component appends events as it
works, and an operations engineer must be able to reconstruct exactly why any
claim got any decision from these events alone (assignment requirement #5).
"""

from typing import Any

from pydantic import BaseModel, Field

from app.contracts.enums import TraceEventType, TraceStatus


class TraceEvent(BaseModel):
    """One recorded step in the pipeline.

    `detail` holds the structured payload (rule inputs, check results,
    extracted values) so the trace is machine-queryable, while `summary`
    stays human-readable for the ops console.
    """

    sequence: int = Field(..., description="Monotonic order within a claim")
    component: str = Field(..., description="Which agent/engine produced this event")
    event_type: TraceEventType
    status: TraceStatus
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ComponentFailure(BaseModel):
    """Record of a component that failed mid-processing and its fallback.

    Surfaced in the API response and reflected in the confidence score
    (assignment requirement #6 / TC011).
    """

    component: str
    error: str
    fallback_used: str
    confidence_penalty: float = Field(
        ..., ge=0, le=1, description="Multiplicative penalty applied to confidence"
    )
