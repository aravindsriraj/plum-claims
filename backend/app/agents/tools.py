"""LangChain @tool definitions for the Clinical Reasoning ReAct Agent.

These tools wrap deterministic policy lookups into standardized LangChain tools,
allowing the ReAct Sub-Agent to inspect policy terms, query exclusion lists,
and verify pre-authorization requirements dynamically during graph execution.
"""

from langchain_core.tools import tool
from app.contracts.enums import ClaimCategory
from app.policy.loader import Policy, load_policy
from app.rules.tagging import match_high_value_test, tag_deterministic

# Default loaded policy instance for tool executions
_POLICY = load_policy()


@tool
def lookup_policy_exclusion(term: str) -> str:
    """Check if a medical diagnosis, treatment, or drug falls under policy exclusions.

    Args:
        term: The diagnosis, treatment, or medicine description to evaluate.
    """
    tags = tag_deterministic(_POLICY, term)
    if tags.exclusions:
        matched = tags.exclusions[0]
        return (
            f"EXCLUDED: '{term}' matches policy exclusion '{matched.entry}'. "
            f"Evidence: '{matched.matched_text}'. Excluded conditions are non-payable."
        )
    return f"COVERED: '{term}' does not match any policy exclusion entry."


@tool
def check_condition_waiting_period(condition: str) -> str:
    """Check the policy-specific waiting period (in days) required for a medical condition.

    Args:
        condition: The medical condition or disease name (e.g. 'diabetes', 'hypertension').
    """
    waiting_days = _POLICY.specific_condition_waiting_days.get(condition.lower())
    if waiting_days is not None:
        return f"WAITING_PERIOD: '{condition}' carries a mandatory {waiting_days}-day waiting period."
    return f"NO_SPECIFIC_WAITING_PERIOD: '{condition}' has no condition-specific waiting period."


@tool
def verify_high_value_test_preauth(test_name: str, amount: float) -> str:
    """Check if a diagnostic imaging test (MRI, CT, PET) requires pre-authorization.

    Args:
        test_name: Diagnostic test description (e.g. 'MRI Brain', 'HRCT Chest').
        amount: The billed or claimed cost of the test in INR.
    """
    matched_test = match_high_value_test(_POLICY, test_name)
    rules = _POLICY.category_rules(ClaimCategory.DIAGNOSTIC)
    threshold = rules.pre_auth_threshold or 10000.0

    if matched_test and amount > threshold:
        return (
            f"PRE_AUTH_REQUIRED: '{test_name}' ({matched_test}, ₹{amount:,.0f}) "
            f"is a high-value test exceeding the ₹{threshold:,.0f} pre-authorization threshold."
        )
    return f"NO_PRE_AUTH_REQUIRED: '{test_name}' (₹{amount:,.0f}) does not require pre-authorization."


def get_clinical_tools() -> list:
    """Return the list of tools for the Clinical Reasoning Agent."""
    return [
        lookup_policy_exclusion,
        check_condition_waiting_period,
        verify_high_value_test_preauth,
    ]
