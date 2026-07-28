"""Exclusion matcher: does the claim involve a policy-excluded condition?

Two passes, in order:
  1. Deterministic alias matching (fast, explainable, used in evals).
  2. (Optional) LLM semantic matching for unseen phrasings — gated behind the
     caller passing an LLM client, and always citing WHICH exclusion entry
     matched so the trace stays accountable.

Either way, the output references the exact policy text that fired.
"""

from pydantic import BaseModel, Field

from app.rules.textnorm import contains_phrase

# Canonical exclusion entry (as written in policy_terms.json) -> aliases.
EXCLUSION_ALIASES: dict[str, list[str]] = {
    "Self-inflicted injuries": ["self inflicted", "self harm", "suicide"],
    "War or nuclear hazard": ["war", "nuclear hazard"],
    "Substance abuse treatment": [
        "substance abuse",
        "drug abuse",
        "alcohol abuse",
        "alcoholism",
        "de addiction",
        "rehabilitation",
    ],
    "Experimental treatments": ["experimental treatment", "clinical trial"],
    "Infertility and assisted reproduction": [
        "infertility",
        "ivf",
        "in vitro fertilization",
        "assisted reproduction",
    ],
    "Obesity and weight loss programs": [
        "obesity",
        "obese",
        "weight loss",
        "weight management",
        "slimming",
        "diet program",
        "diet plan",
        "diet and nutrition",
        "nutrition program",
    ],
    "Bariatric surgery": ["bariatric"],
    "Cosmetic or aesthetic procedures": [
        "cosmetic",
        "aesthetic",
        "teeth whitening",
        "whitening",
        "veneers",
        "bleaching",
    ],
    "Vaccination (non-medically necessary)": ["vaccination", "vaccine", "immunization"],
    "Health supplements and tonics": ["health supplement", "supplements", "tonic", "multivitamin"],
}


class ExclusionMatch(BaseModel):
    """A fired exclusion, citing the exact policy text."""

    policy_entry: str = Field(..., description="Verbatim exclusion text from policy_terms.json")
    matched_text: str = Field(..., description="The document text that triggered the match")
    via: str = Field(..., description="'deterministic' or 'llm' — how the match was found")


class LlmExclusionVerdict(BaseModel):
    """Structured output schema for the semantic-matching fallback."""

    is_excluded: bool
    matched_policy_entry: str | None = Field(
        default=None, description="Must be copied verbatim from the provided exclusion list"
    )
    rationale: str = ""


def match_exclusions_deterministic(
    excluded_conditions: list[str], *texts: str | None
) -> list[ExclusionMatch]:
    """Pass 1: alias-based matching. Only matches aliases whose canonical
    entry actually exists in the loaded policy (no invented rules)."""
    matches: list[ExclusionMatch] = []
    policy_entries = set(excluded_conditions)
    for entry, aliases in EXCLUSION_ALIASES.items():
        if entry not in policy_entries:
            continue  # alias table is a superset; policy file is the authority
        for text in texts:
            if text and any(contains_phrase(text, alias) for alias in aliases):
                matches.append(
                    ExclusionMatch(
                        policy_entry=entry, matched_text=text, via="deterministic"
                    )
                )
                break
    return matches
