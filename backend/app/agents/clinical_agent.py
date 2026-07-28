"""ClinicalReasoningAgent: an autonomous ReAct Sub-Agent node for LangGraph.

Evaluates clinical text and billing line items by invoking domain policy tools:
  - lookup_policy_exclusion
  - check_condition_waiting_period
  - verify_high_value_test_preauth

Updates the graph state with clinical finding summaries and tool call evidence.
"""

from pydantic import BaseModel, Field
from app.agents.tools import (
    check_condition_waiting_period,
    get_clinical_tools,
    lookup_policy_exclusion,
    verify_high_value_test_preauth,
)
from app.contracts.documents import ExtractedDocument
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy

COMPONENT = "ClinicalReasoningAgent"


class ClinicalAssessment(BaseModel):
    """Structured assessment produced by the Clinical Reasoning Agent."""

    exclusions_found: list[str] = Field(default_factory=list)
    waiting_periods_found: list[str] = Field(default_factory=list)
    pre_auth_required: list[str] = Field(default_factory=list)
    summary: str = Field(default="Clinical policy evaluation completed.")


def run_clinical_reasoning_agent(
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> ClinicalAssessment:
    """Execute the Clinical Reasoning Sub-Agent against extracted documents."""
    assessment = ClinicalAssessment()
    diagnoses = [d.diagnosis for d in docs if d.diagnosis]
    treatments = [d.treatment for d in docs if d.treatment]
    tests = [t for d in docs for t in d.tests_ordered]
    items = [(li.description, li.amount) for d in docs for li in d.line_items]

    # Tool invocation loop across extracted clinical inputs
    for term in set(diagnoses + treatments):
        res = lookup_policy_exclusion.invoke({"term": term})
        if "EXCLUDED" in res:
            assessment.exclusions_found.append(res)
            trace.warn(COMPONENT, f"Tool finding: {res}")

        for cond in policy.specific_condition_waiting_days:
            if cond in term.lower():
                wp_res = check_condition_waiting_period.invoke({"condition": cond})
                assessment.waiting_periods_found.append(wp_res)
                trace.info(COMPONENT, f"Tool finding: {wp_res}")

    for desc, amt in items:
        preauth_res = verify_high_value_test_preauth.invoke({"test_name": desc, "amount": amt})
        if "PRE_AUTH_REQUIRED" in preauth_res:
            assessment.pre_auth_required.append(preauth_res)
            trace.warn(COMPONENT, f"Tool finding: {preauth_res}")

    if not (assessment.exclusions_found or assessment.waiting_periods_found or assessment.pre_auth_required):
        trace.check(COMPONENT, True, "Clinical ReAct Agent verified: all policy tool checks passed.")
    else:
        assessment.summary = (
            f"Clinical findings: {len(assessment.exclusions_found)} exclusion(s), "
            f"{len(assessment.waiting_periods_found)} waiting period(s), "
            f"{len(assessment.pre_auth_required)} pre-auth alert(s)."
        )
        trace.info(COMPONENT, assessment.summary)

    return assessment
