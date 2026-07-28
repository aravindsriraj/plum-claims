"""ReAct Claims Investigation Subagent.

Uses an interactive ReAct (Reasoning + Acting) loop with tools to perform
deep-dive investigations on complex or flagged claims (e.g. claims routed to
MANUAL_REVIEW or flagged with fraud signals).

Tools available to the ReAct agent:
  1. `lookup_policy_rules`: Query policy terms for limits, co-pays, and waiting periods.
  2. `check_member_history`: Query past claim history and velocity for a member.
  3. `verify_provider_network`: Check hospital network status and discount rates.
"""

from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.contracts.inputs import ClaimInput
from app.llm.client import DEFAULT_MODEL
from app.policy.loader import Policy


def build_investigation_tools(policy: Policy, claim: ClaimInput):
    """Build bound tool functions that give the ReAct agent access to policy and claim context."""

    @tool
    def lookup_policy_rules(category: str) -> str:
        """Look up policy coverage rules, sub-limits, co-pay, and pre-auth requirements for a claim category."""
        try:
            rules = policy.category_rules(category) # type: ignore
            return (
                f"Policy {policy.policy_id} for {category}: "
                f"Sub-limit ₹{rules.sub_limit:,.0f}, Co-pay {rules.copay_percent}%, "
                f"Pre-auth required: {rules.requires_pre_auth}, "
                f"Exclusions: {rules.excluded_procedures or 'none'}."
            )
        except Exception as e:
            return f"Error retrieving rules for {category}: {e}"

    @tool
    def check_member_history(member_id: str) -> str:
        """Look up member tenure, join date, and prior claim submission history."""
        member = policy.find_member(member_id)
        if not member:
            return f"Member {member_id} not found in policy roster."
        join_date = policy.member_join_date(member)
        prior_claims = claim.claims_history
        return (
            f"Member {member.name} ({member_id}): Joined on {join_date}. "
            f"Prior claims in history: {len(prior_claims)} claim(s), total ₹{sum(c.amount for c in prior_claims):,.0f}."
        )

    @tool
    def verify_provider_network(hospital_name: str) -> str:
        """Verify whether a hospital/provider is in the preferred network list."""
        network_list = policy.network_hospitals
        matched = any(hospital_name.lower() in h.lower() or h.lower() in hospital_name.lower() for h in network_list)
        return (
            f"Provider '{hospital_name}' IS in the preferred network (discount applies)."
            if matched
            else f"Provider '{hospital_name}' is NOT in the preferred network list."
        )

    return [lookup_policy_rules, check_member_history, verify_provider_network]


class ReActInvestigationResult(BaseModel):
    summary: str
    steps_taken: int


def run_react_investigation(
    claim: ClaimInput, policy: Policy, prompt: str
) -> str:
    """Execute a ReAct reasoning loop to investigate a claim query."""
    llm = ChatGoogleGenerativeAI(model=DEFAULT_MODEL, temperature=0)
    tools = build_investigation_tools(policy, claim)
    agent = create_react_agent(llm, tools)

    inputs = {"messages": [("user", prompt)]}
    result = agent.invoke(inputs)

    messages = result.get("messages", [])
    if messages:
        return messages[-1].content
    return "ReAct investigation completed with no output."
