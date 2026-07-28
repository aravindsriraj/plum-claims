"""Text normalization shared by the deterministic matchers.

All policy matching (exclusions, waiting-period conditions, procedures,
network hospitals) goes through these helpers so casing, punctuation and
word order never cause false misses or false hits.
"""

import re


def normalize(text: str | None) -> str:
    """Lowercase, collapse whitespace, strip punctuation except slashes."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9/\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(haystack: str | None, phrase: str) -> bool:
    """True if `phrase` appears in `haystack` on word boundaries.

    Word boundaries matter clinically: 'hernia' must match 'inguinal hernia'
    but NOT 'lumbar disc herniation' (a spinal condition, not a hernia), and
    'joint' alone must never satisfy a 'joint replacement' check.
    """
    hay = normalize(haystack)
    needle = normalize(phrase)
    if not hay or not needle:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", hay) is not None
