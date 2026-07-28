"""Resilience wrapper: no single component may crash the pipeline.

Every graph node that can fail (LLM calls, parsing, validation) runs through
`run_resilient`. On exception it:
  1. records a ComponentFailure in the trace (visible in the API response),
  2. returns the caller-supplied fallback so the pipeline continues with
     whatever it has,
  3. applies a confidence penalty via the confidence model.

This is the mechanism TC011 exercises via `simulate_component_failure`.
"""

from collections.abc import Callable
from typing import TypeVar

from app.contracts.trace import ComponentFailure
from app.observability.trace import TraceRecorder

T = TypeVar("T")

# How much a single component failure erodes confidence. 0.25 means one
# failure multiplies the score by 0.75.
DEFAULT_FAILURE_PENALTY = 0.25


def run_resilient(
    component: str,
    fn: Callable[[], T],
    fallback: Callable[[], T],
    trace: TraceRecorder,
    penalty: float = DEFAULT_FAILURE_PENALTY,
    fallback_description: str = "component skipped; pipeline continued with partial data",
) -> T:
    """Run `fn`; on any exception, record the failure and return `fallback()`.

    `fn` and `fallback` take no arguments — close over the state you need.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — catching everything is the point here
        trace.record_failure(
            ComponentFailure(
                component=component,
                error=f"{type(exc).__name__}: {exc}",
                fallback_used=fallback_description,
                confidence_penalty=penalty,
            )
        )
        return fallback()
