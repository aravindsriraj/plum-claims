"""Semantic tagging: maps clinical free-text onto the policy vocabulary.

This module owns the ONLY text-matching logic for conditions, exclusions and
procedure lists. Two producers feed it:

  1. Deterministic matcher — word-boundary alias matching using the alias
     tables in policy_terms.json (matching_aliases). Fast, reproducible, and
     the ONLY tagger available in provided-content (eval) mode.
  2. LLM semantic read — the vision extraction call also returns tags, which
     are validated against the policy vocabulary (hallucinated entries are
     dropped and flagged) and merged with the deterministic tags.

Merge semantics (hybrid): UNION. The deterministic matcher is the precision
floor — it can only fire on curated aliases, so its hits are trusted. The LLM
adds recall for phrasings no alias anticipates ("high sugar" -> diabetes).
Any disagreement between the two is surfaced as a warning string; nothing is
silently resolved.

Judgment — what to DO with a tag (reject, cap, wait) — never lives here.
"""

from pydantic import BaseModel, Field

from app.contracts.documents import DocumentTags, PolicyTag
from app.policy.loader import Policy
from app.rules.textnorm import contains_normalized, normalize


class TagMergeResult(BaseModel):
    """Merged tags plus human-readable disagreement warnings."""

    tags: DocumentTags = Field(default_factory=DocumentTags)
    warnings: list[str] = Field(default_factory=list)


def match_high_value_test(policy: Policy, description: str | None) -> str | None:
    """The canonical high-value test a line-item description refers to, or None.

    Alias-based, so "Magnetic Resonance Imaging (Brain)" resolves to MRI just
    as "MRI Brain" does — the pre-auth JUDGMENT (threshold comparison) stays
    in the adjudicator; only recognition lives here.
    """
    hay = normalize(description)
    if not hay:
        return None
    for name, aliases in policy.high_value_test_aliases.items():
        candidates = [normalize(name), *aliases]
        if any(contains_normalized(hay, a) for a in candidates if a):
            return name
    return None


def is_consultation_fee(policy: Policy, description: str | None) -> bool:
    """True if a line item is a consultation/doctor-visit fee.

    Alias-based ("OPD visit fee", "doctor charges", ...), so the consultation
    sub-limit caps the right portion even when bills don't say the literal
    word 'consultation'.
    """
    hay = normalize(description)
    if not hay:
        return False
    return any(
        contains_normalized(hay, alias)
        for alias in policy.consultation_fee_aliases
        if alias
    )


def tag_line_items(
    policy: Policy, line_items: list, known_tests: list[str] | None = None
) -> list[str]:
    """Fill per-line perception tags in place; return warnings.

    Union semantics per field: an LLM-set value is kept (after validation —
    a high-value-test tag must name a test the policy actually lists), and
    any field the LLM left unset is filled by the deterministic matcher.
    Used by extraction in BOTH modes, so the adjudicator always sees tags.
    """
    warnings: list[str] = []
    valid_tests = set(known_tests or policy.high_value_test_aliases.keys())
    for li in line_items:
        if getattr(li, "is_consultation_fee", None) is None:
            li.is_consultation_fee = is_consultation_fee(policy, li.description)
        tag = getattr(li, "matched_high_value_test", None)
        if tag is not None and tag not in valid_tests:
            warnings.append(
                f"LLM tagged '{li.description}' as unknown high-value test "
                f"'{tag}' — dropped; deterministic matcher re-evaluated it."
            )
            tag = None
        if tag is None:
            tag = match_high_value_test(policy, li.description)
        li.matched_high_value_test = tag
    return warnings


def tag_deterministic(policy: Policy, *texts: str | None) -> DocumentTags:
    """Alias-based tagging of clinical text against the policy vocabulary.

    Only aliases whose canonical key/entry actually exists in the loaded
    policy are considered — the policy file is the authority, the alias table
    merely describes phrasings of it. Texts are normalized once each.
    """
    haystacks = [normalize(t) for t in texts if t]

    # Conditions: alias key must be a real specific-condition in this policy.
    valid_conditions = set(policy.specific_condition_waiting_days)
    conditions: list[str] = []
    for key, aliases in policy.condition_aliases.items():
        if key not in valid_conditions:
            continue
        if any(
            contains_normalized(hay, alias)
            for hay in haystacks
            for alias in aliases
        ):
            conditions.append(key)

    # Exclusions: alias entry must be a verbatim exclusion in this policy.
    valid_entries = set(policy.excluded_conditions)
    exclusions: list[PolicyTag] = []
    raw_texts = [t for t in texts if t]
    for entry, aliases in policy.exclusion_aliases.items():
        if entry not in valid_entries:
            continue
        for norm_hay, raw in zip(haystacks, raw_texts):
            if any(contains_normalized(norm_hay, alias) for alias in aliases):
                exclusions.append(
                    PolicyTag(entry=entry, matched_text=raw, via="deterministic")
                )
                break
    return DocumentTags(conditions=conditions, exclusions=exclusions)


def merge_tags(
    llm_tags: DocumentTags | None,
    det_tags: DocumentTags,
    file_id: str = "",
) -> TagMergeResult:
    """Union-merge LLM and deterministic tags, flagging disagreements.

    - Conditions: union of keys, deterministic order first (stable trace).
    - Exclusions: union by policy entry; an entry found by both sides is
      marked via='both' (corroborated), otherwise credited to its finder.
    - Any asymmetric coverage becomes a warning: LLM recall wins and
      deterministic-only catches are both worth an auditor's eye.
    """
    result = TagMergeResult()
    if llm_tags is None:
        result.tags = det_tags
        return result

    where = f" in {file_id}" if file_id else ""

    # --- conditions -------------------------------------------------------
    merged_conditions = list(det_tags.conditions)
    for key in llm_tags.conditions:
        if key not in merged_conditions:
            merged_conditions.append(key)
            result.warnings.append(
                f"Semantic tagger found condition '{key}'{where} that the "
                f"deterministic matcher missed (alias gap) — accepted via LLM."
            )

    # --- exclusions -------------------------------------------------------
    by_entry: dict[str, PolicyTag] = {t.entry: t for t in det_tags.exclusions}
    for tag in llm_tags.exclusions:
        existing = by_entry.get(tag.entry)
        if existing is None:
            by_entry[tag.entry] = tag
            result.warnings.append(
                f"Semantic tagger matched exclusion '{tag.entry}'{where} that "
                f"the deterministic matcher missed — accepted via LLM."
            )
        else:
            by_entry[tag.entry] = existing.model_copy(update={"via": "both"})

    result.tags = DocumentTags(
        conditions=merged_conditions, exclusions=list(by_entry.values())
    )
    return result


def validate_llm_tags(raw: DocumentTags, policy: Policy) -> tuple[DocumentTags, list[str]]:
    """Whitelist-check LLM-produced tags against the policy vocabulary.

    The model is instructed to copy policy entries verbatim, but it is never
    trusted blindly: any tag that is not an actual policy key/entry is dropped
    and flagged. Returns (clean_tags, warnings).
    """
    warnings: list[str] = []

    valid_conditions = set(policy.specific_condition_waiting_days)
    conditions: list[str] = []
    for key in raw.conditions:
        if key in valid_conditions:
            conditions.append(key)
        else:
            warnings.append(
                f"LLM produced unknown condition tag '{key}' — dropped "
                f"(not in the policy's specific-conditions list)."
            )

    valid_entries = set(policy.excluded_conditions)
    exclusions: list[PolicyTag] = []
    for tag in raw.exclusions:
        if tag.entry in valid_entries:
            exclusions.append(tag.model_copy(update={"via": "llm"}))
        else:
            warnings.append(
                f"LLM produced unknown exclusion '{tag.entry}' — dropped "
                f"(not a verbatim policy exclusion)."
            )
    return DocumentTags(conditions=conditions, exclusions=exclusions), warnings
