"""TraceRecorder: the append-only audit log every component writes into.

One recorder lives for the duration of a claim. Components never print or
log ad-hoc — they record events here, and the events become both the API
`trace` field and the input to the ExplanationBuilder.

Thread-safe: LangGraph `Send` workers may append concurrently.
"""

import threading
from typing import Any

from app.contracts.enums import TraceEventType, TraceStatus
from app.contracts.trace import ComponentFailure, TraceEvent


class TraceRecorder:
    """Collects TraceEvents in order. Safe for parallel document workers."""

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self.failures: list[ComponentFailure] = []
        self.llm_calls: int = 0
        self._lock = threading.Lock()

    def record(
        self,
        component: str,
        event_type: TraceEventType,
        status: TraceStatus,
        summary: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._events.append(
                TraceEvent(
                    sequence=len(self._events) + 1,
                    component=component,
                    event_type=event_type,
                    status=status,
                    summary=summary,
                    detail=detail or {},
                )
            )

    # Convenience wrappers so call sites read naturally.
    def check(self, component: str, passed: bool, summary: str, detail: dict | None = None) -> None:
        self.record(
            component,
            TraceEventType.CHECK,
            TraceStatus.PASS if passed else TraceStatus.FAIL,
            summary,
            detail,
        )

    def info(self, component: str, summary: str, detail: dict | None = None) -> None:
        self.record(component, TraceEventType.INFO, TraceStatus.PASS, summary, detail)

    def warn(self, component: str, summary: str, detail: dict | None = None) -> None:
        self.record(component, TraceEventType.CHECK, TraceStatus.WARN, summary, detail)

    def skipped(self, component: str, summary: str, detail: dict | None = None) -> None:
        self.record(component, TraceEventType.CHECK, TraceStatus.SKIPPED, summary, detail)

    def error(self, component: str, summary: str, detail: dict | None = None) -> None:
        self.record(component, TraceEventType.ERROR, TraceStatus.FAIL, summary, detail)

    def record_failure(self, failure: ComponentFailure) -> None:
        """Register a component failure both in the event stream and the
        dedicated failures list that drives confidence and the response."""
        with self._lock:
            self.failures.append(failure)
        self.record(
            failure.component,
            TraceEventType.ERROR,
            TraceStatus.FAIL,
            f"Component failed and was skipped: {failure.error}. Fallback: {failure.fallback_used}.",
            {"confidence_penalty": failure.confidence_penalty},
        )

    @property
    def events(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._events)
