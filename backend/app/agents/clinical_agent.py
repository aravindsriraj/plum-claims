"""ClinicalTaggingAgent: tool-calling agent for clinical perception.

When an LLM is configured, maps diagnoses/treatments onto the policy
vocabulary via deterministic lookup tools, then union-merges validated tags
into documents. Without an LLM (evals), this is a no-op.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.contracts.documents import DocumentTags, ExtractedDocument, PolicyTag
from app.llm.client import LlmClient
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.tagging import match_high_value_test, merge_tags, tag_deterministic, validate_llm_tags

COMPONENT = "ClinicalTaggingAgent"

SYSTEM_PROMPT = """You are a clinical policy tagging specialist for Indian health insurance.
Your ONLY job is perception: map diagnoses, treatments, medicines, and billed
tests onto the insurer's policy vocabulary using the provided tools.

Rules:
- Call tools to verify exclusions, waiting-period conditions, and high-value tests.
- Never invent policy entries — only return keys/entries the tools confirm.
- Never calculate co-pays, waiting dates, or approve/reject amounts.
- Prefer precision: empty lists are better than guesses.
"""


class ClinicalExclusionFinding(BaseModel):
    entry: str = Field(..., description="Verbatim policy exclusion entry")
    evidence: str = Field(default="", description="Document text that triggered the match")


class ClinicalTaggingResult(BaseModel):
    conditions: list[str] = Field(default_factory=list)
    exclusions: list[ClinicalExclusionFinding] = Field(default_factory=list)
    high_value_tests: list[str] = Field(default_factory=list)
    summary: str = Field(default="Clinical tagging completed.")


def build_clinical_tools(policy: Policy) -> list:
    @tool
    def lookup_policy_exclusion(term: str) -> str:
        """Check whether clinical text matches a policy exclusion."""
        tags = tag_deterministic(policy, term)
        if tags.exclusions:
            matched = tags.exclusions[0]
            return (
                f"EXCLUDED: '{term}' matches '{matched.entry}'. "
                f"Evidence: '{matched.matched_text}'."
            )
        return f"COVERED: '{term}' does not match any exclusion."

    @tool
    def check_condition_waiting_period(condition: str) -> str:
        """Look up a condition-specific waiting period (key or free text)."""
        key = condition.strip().lower().replace(" ", "_")
        days = policy.specific_condition_waiting_days.get(key)
        if days is not None:
            return f"WAITING_PERIOD: '{key}' requires {days} days after join."
        tags = tag_deterministic(policy, condition)
        if tags.conditions:
            hits = [
                f"{c}={policy.specific_condition_waiting_days.get(c)}d"
                for c in tags.conditions
            ]
            return f"MATCHED_CONDITIONS: {', '.join(hits)}"
        return f"NO_SPECIFIC_WAITING_PERIOD: '{condition}'."

    @tool
    def verify_high_value_test(test_name: str) -> str:
        """Check whether a test is a high-value imaging test (MRI/CT/PET)."""
        matched = match_high_value_test(policy, test_name)
        if matched:
            return f"HIGH_VALUE_TEST: '{test_name}' → '{matched}'."
        return f"NOT_HIGH_VALUE: '{test_name}'."

    @tool
    def list_waiting_condition_keys() -> str:
        """List every specific-condition waiting-period key on the policy."""
        items = [f"{k}={v}d" for k, v in sorted(policy.specific_condition_waiting_days.items())]
        return "CONDITION_KEYS: " + (", ".join(items) if items else "(none)")

    return [
        lookup_policy_exclusion,
        check_condition_waiting_period,
        verify_high_value_test,
        list_waiting_condition_keys,
    ]


def _clinical_prompt(docs: list[ExtractedDocument]) -> str:
    blocks = []
    for d in docs:
        items = "; ".join(f"{li.description} (₹{li.amount:,.0f})" for li in d.line_items) or "(none)"
        blocks.append(
            f"Document {d.file_id} ({d.doc_type.value}):\n"
            f"  diagnosis: {d.diagnosis or '(none)'}\n"
            f"  treatment: {d.treatment or '(none)'}\n"
            f"  medicines: {', '.join(d.medicines) or '(none)'}\n"
            f"  tests_ordered: {', '.join(d.tests_ordered) or '(none)'}\n"
            f"  line_items: {items}"
        )
    return (
        "Tag the following claim documents onto the policy vocabulary. "
        "Use tools before finalizing.\n\n" + "\n\n".join(blocks)
    )


def enrich_documents_with_clinical_tags(
    docs: list[ExtractedDocument],
    result: ClinicalTaggingResult,
    policy: Policy,
    trace: TraceRecorder,
) -> list[ExtractedDocument]:
    raw = DocumentTags(
        conditions=list(result.conditions),
        exclusions=[
            PolicyTag(entry=e.entry, matched_text=e.evidence or e.entry, via="llm")
            for e in result.exclusions
        ],
    )
    clean, warnings = validate_llm_tags(raw, policy)
    for warning in warnings:
        trace.warn(COMPONENT, warning)

    valid_tests = set(policy.high_value_test_aliases)
    agent_tests = {t for t in result.high_value_tests if t in valid_tests}
    for name in result.high_value_tests:
        if name not in valid_tests:
            trace.warn(COMPONENT, f"Dropped unknown high-value test tag '{name}'.")

    updated: list[ExtractedDocument] = []
    for d in docs:
        line_items = list(d.line_items)
        for li in line_items:
            if li.matched_high_value_test is None:
                matched = match_high_value_test(policy, li.description)
                if matched in agent_tests:
                    li.matched_high_value_test = matched
        merged = merge_tags(clean, d.tags or DocumentTags(), file_id=d.file_id)
        for warning in merged.warnings:
            trace.warn(COMPONENT, warning)
        updated.append(d.model_copy(update={"tags": merged.tags, "line_items": line_items}))

    trace.info(
        COMPONENT,
        result.summary
        or (
            f"Clinical agent tags merged: conditions={clean.conditions}, "
            f"exclusions={[e.entry for e in clean.exclusions]}."
        ),
        {
            "conditions": clean.conditions,
            "exclusions": [e.entry for e in clean.exclusions],
            "high_value_tests": sorted(agent_tests),
        },
    )
    return updated


def run_clinical_tagging_agent(
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> list[ExtractedDocument]:
    if llm is None:
        trace.skipped(
            COMPONENT,
            "No LLM configured — clinical agent skipped; deterministic tags retained.",
        )
        return docs
    if not docs:
        return docs

    agent = create_agent(
        model=llm._chat,
        tools=build_clinical_tools(policy),
        system_prompt=SYSTEM_PROMPT,
        response_format=ClinicalTaggingResult,
        name="clinical_tagging_agent",
    )
    raw = agent.invoke(
        {"messages": [{"role": "user", "content": _clinical_prompt(docs)}]},
        config={
            "run_name": "clinical_tagging_agent",
            "tags": ["clinical", "agent"],
            "metadata": {"document_count": len(docs)},
            "recursion_limit": 16,
        },
    )
    structured = raw.get("structured_response")
    if structured is None:
        trace.warn(COMPONENT, "Clinical agent returned no structured_response; tags unchanged.")
        return docs
    if isinstance(structured, dict):
        structured = ClinicalTaggingResult.model_validate(structured)
    return enrich_documents_with_clinical_tags(docs, structured, policy, trace)
