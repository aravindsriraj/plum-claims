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
    return contains_normalized(normalize(haystack), normalize(phrase))


def contains_normalized(haystack_norm: str, needle_norm: str) -> bool:
    """Word-boundary match when both sides are ALREADY normalized.

    The policy loader ships pre-normalized aliases, so per-claim matching
    normalizes each document text once and reuses it across all needles.
    """
    if not haystack_norm or not needle_norm:
        return False
    return re.search(rf"\b{re.escape(needle_norm)}\b", haystack_norm) is not None
