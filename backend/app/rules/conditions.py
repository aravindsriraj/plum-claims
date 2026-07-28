"""Medical-condition matcher: maps free-text diagnoses/treatments to the
condition keys used in the policy's `waiting_periods.specific_conditions`.

Deterministic and phrase-based. Aliases are deliberately PRECISE — e.g.
"joint_replacement" matches "knee replacement" but NOT "chronic joint pain"
(TC011 depends on this distinction). When nothing matches, the claim simply
has no specific-condition waiting period.
"""

from app.rules.textnorm import contains_phrase

# Policy condition key -> phrases that indicate it (matched against normalized text).
CONDITION_ALIASES: dict[str, list[str]] = {
    "diabetes": ["diabetes", "diabetic", "t2dm", "t1dm", "type 2 diabetes", "type 1 diabetes"],
    "hypertension": ["hypertension", "htn", "high blood pressure"],
    "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid"],
    # Phrase-level: "joint pain" or "joint replacement" are different worlds.
    "joint_replacement": [
        "joint replacement",
        "knee replacement",
        "hip replacement",
        "arthroplasty",
    ],
    "maternity": ["maternity", "pregnancy", "pregnant", "delivery", "obstetric", "antenatal"],
    "mental_health": ["mental health", "depression", "anxiety disorder", "psychiatric"],
    "obesity_treatment": ["obesity", "obese", "bariatric", "weight loss", "morbid obesity"],
    "hernia": ["hernia"],
    "cataract": ["cataract"],
}


def match_conditions(*texts: str | None) -> list[str]:
    """Return the policy condition keys present in any of the given texts.

    Input: diagnosis, treatment, line-item descriptions — whatever clinical
    text the extraction produced. Order is stable (alias-map order) so the
    trace is deterministic.
    """
    matched: list[str] = []
    for condition, aliases in CONDITION_ALIASES.items():
        if any(contains_phrase(text, alias) for text in texts for alias in aliases):
            matched.append(condition)
    return matched
