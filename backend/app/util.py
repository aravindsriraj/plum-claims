"""Small shared helpers with no better home."""

from datetime import date
from typing import Any


def parse_iso_date(value: Any) -> date | None:
    """Best-effort ISO date parse; anything unparseable becomes None.

    Callers decide what None means (unreadable field, unavailable data) —
    this helper never raises on messy input.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
