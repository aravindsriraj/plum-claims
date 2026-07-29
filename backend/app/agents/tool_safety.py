"""Shared reliability rail for tool-calling agents.

Agents choose their own tool sequence; this closes the gap when the model
skips a step that downstream code depends on, by invoking the missing
tool(s) directly. Used by every agent in this package.
"""

from __future__ import annotations

from app.observability.trace import TraceRecorder


def run_missing_required_tools(
    required_tools: tuple[str, ...],
    called: set[str],
    tools: list,
    trace: TraceRecorder,
    component: str,
) -> None:
    """Invoke any required tool the agent's loop skipped, in order."""
    by_name = {t.name: t for t in tools}
    for name in required_tools:
        if name in called:
            continue
        trace.warn(component, f"Agent skipped {name} — running deterministically.")
        by_name[name].invoke({})
