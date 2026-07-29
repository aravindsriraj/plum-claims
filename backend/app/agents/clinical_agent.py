"""ClinicalTaggingAgent: LLM tool-calling agent with LLM-powered perception tools.

When an LLM is configured, maps diagnoses/treatments onto the policy
vocabulary via tool-calling agent using specialized LLM-powered classification
tools, then union-merges validated tags into documents. Without an LLM (evals),
this is a no-op.
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

SYSTEM_PROMPT_TEMPLATE = """You are a clinical policy tagging specialist for Indian health insurance.
Your ONLY job is perception: map medical diagnoses, treatments, medicines, and billed tests onto the insurer's exact policy vocabulary provided below.

### MASTER POLICY EXCLUSIONS (Verbatim policy entries):
{exclusions_list}

### SPECIFIC WAITING PERIOD CONDITIONS (Exact policy condition keys):
{conditions_list}

### HIGH-VALUE TESTS (> ₹10,000 threshold requiring pre-auth):
{high_value_tests_list}

### RULES:
1. Call your available tools (`lookup_policy_exclusion`, `check_condition_waiting_period`, `verify_high_value_test`) to classify clinical terms.
2. Carefully read the OCR document data (diagnosis, treatment, medicines, and tests/line items).
3. Match clinical phrasing and diagnosis text against the MASTER POLICY EXCLUSIONS and SPECIFIC WAITING PERIOD CONDITIONS.
4. Never invent policy entries — only return entries or keys present in the master lists above.
5. Exclusions apply ONLY to document-level primary diagnoses/conditions (e.g., Obesity, Infertility, Dental surgery).
6. Do NOT mark individual line-item procedures as overall document exclusions.
7. Never calculate co-pays, waiting dates, or financial approval/rejection amounts.
8. Precision is better than guessing: return empty lists if no conditions or exclusions apply.
"""


class ClinicalExclusionFinding(BaseModel):
    entry: str = Field(..., description="Verbatim policy exclusion entry from master list")
    evidence: str = Field(default="", description="Document text that triggered the match")


class ClinicalTaggingResult(BaseModel):
    conditions: list[str] = Field(default_factory=list, description="Exact policy condition keys identified (e.g. 'diabetes')")
    exclusions: list[ClinicalExclusionFinding] = Field(default_factory=list, description="Exclusions identified")
    high_value_tests: list[str] = Field(default_factory=list, description="High-value tests identified (e.g. 'CT Scan', 'MRI')")
    summary: str = Field(default="Clinical tagging completed.")


class ToolExclusionClassification(BaseModel):
    is_excluded: bool = Field(description="True if the clinical text matches any verbatim policy exclusion")
    matched_entry: str = Field(default="", description="Exact verbatim entry from master policy exclusion list if matched, else empty")
    explanation: str = Field(default="", description="Brief explanation of the clinical reasoning")


class ToolConditionClassification(BaseModel):
    is_matched: bool = Field(description="True if the clinical diagnosis matches any specific waiting period condition key")
    matched_key: str = Field(default="", description="Exact condition key (e.g. 'diabetes', 'hypertension') if matched, else empty")
    explanation: str = Field(default="", description="Brief explanation of the clinical reasoning")


class ToolTestClassification(BaseModel):
    is_high_value: bool = Field(description="True if the test is a high-value imaging test like CT Scan, MRI, PET Scan")
    matched_test: str = Field(default="", description="Exact test name (e.g. 'CT Scan', 'MRI', 'PET Scan') if matched, else empty")
    explanation: str = Field(default="", description="Brief explanation of the classification")


def build_clinical_tools(policy: Policy, llm: LlmClient | None = None) -> list:
    @tool
    def lookup_policy_exclusion(term: str) -> str:
        """Check whether clinical text matches a policy exclusion using AI semantic classification."""
        if llm is not None:
            exclusions_text = "\n".join(f"- {e}" for e in sorted(policy.excluded_conditions))
            prompt = (
                f"Identify if the following clinical text falls under any policy exclusion.\n\n"
                f"MASTER POLICY EXCLUSIONS:\n{exclusions_text}\n\n"
                f"CLINICAL TEXT TO EVALUATE: '{term}'\n"
            )
            try:
                res = llm._chat.with_structured_output(ToolExclusionClassification).invoke(prompt)
                if res and res.is_excluded and res.matched_entry in policy.excluded_conditions:
                    return (
                        f"EXCLUDED: '{term}' matches '{res.matched_entry}'. "
                        f"Explanation: {res.explanation}"
                    )
            except Exception:
                pass

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
        """Look up a condition-specific waiting period (key or free text) using AI semantic classification."""
        if llm is not None:
            conditions_text = "\n".join(f"- Key: '{k}' ({v} days waiting)" for k, v in sorted(policy.specific_condition_waiting_days.items()))
            prompt = (
                f"Map the following diagnosis/condition text onto the exact policy condition keys.\n\n"
                f"POLICY CONDITION KEYS:\n{conditions_text}\n\n"
                f"DIAGNOSIS TEXT TO EVALUATE: '{condition}'\n"
            )
            try:
                res = llm._chat.with_structured_output(ToolConditionClassification).invoke(prompt)
                if res and res.is_matched and res.matched_key in policy.specific_condition_waiting_days:
                    days = policy.specific_condition_waiting_days[res.matched_key]
                    return f"WAITING_PERIOD: '{res.matched_key}' requires {days} days after join. Explanation: {res.explanation}"
            except Exception:
                pass

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
        """Check whether a test is a high-value imaging test (MRI/CT/PET) using AI semantic classification."""
        if llm is not None:
            tests_text = ", ".join(sorted(policy.high_value_test_aliases.keys()))
            prompt = (
                f"Determine if the test description corresponds to any high-value imaging test category.\n\n"
                f"HIGH-VALUE TEST CATEGORIES: {tests_text}\n\n"
                f"TEST DESCRIPTION TO EVALUATE: '{test_name}'\n"
            )
            try:
                res = llm._chat.with_structured_output(ToolTestClassification).invoke(prompt)
                if res and res.is_high_value and res.matched_test in policy.high_value_test_aliases:
                    return f"HIGH_VALUE_TEST: '{test_name}' → '{res.matched_test}'. Explanation: {res.explanation}"
            except Exception:
                pass

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
        blocks.append(
            f"Document {d.file_id} ({d.doc_type.value}):\n"
            f"  diagnosis: {d.diagnosis or '(none)'}\n"
            f"  treatment: {d.treatment or '(none)'}\n"
            f"  medicines: {', '.join(d.medicines) or '(none)'}\n"
            f"  tests_ordered: {', '.join(d.tests_ordered) or '(none)'}"
        )
    return (
        "Tag the following claim documents onto the provided policy vocabulary. "
        "Use your tools (`lookup_policy_exclusion`, `check_condition_waiting_period`, `verify_high_value_test`) "
        "to evaluate diagnoses and clinical phrasing before finalizing.\n\n" + "\n\n".join(blocks)
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

    exclusions_list = "\n".join(f"- {e}" for e in sorted(policy.excluded_conditions)) or "(none)"
    conditions_list = "\n".join(f"- Key: '{k}' ({v} days waiting)" for k, v in sorted(policy.specific_condition_waiting_days.items())) or "(none)"
    tests_list = ", ".join(sorted(policy.high_value_test_aliases.keys())) or "(none)"

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        exclusions_list=exclusions_list,
        conditions_list=conditions_list,
        high_value_tests_list=tests_list,
    )

    try:
        tools = build_clinical_tools(policy, llm)
        agent = create_agent(
            model=llm._chat,
            tools=tools,
            system_prompt=system_prompt,
            response_format=ClinicalTaggingResult,
            name="clinical_tagging_agent",
        )
        raw = agent.invoke(
            {"messages": [("user", _clinical_prompt(docs))]},
            config={
                "run_name": "clinical_tagging_agent",
                "tags": ["clinical", "agent"],
                "metadata": {"document_count": len(docs)},
                "recursion_limit": 16,
            },
        )
        structured = raw.get("structured_response")
        if structured is None:
            # Fallback to direct structured call if tool-agent produced no structured response
            structured_llm = llm._chat.with_structured_output(ClinicalTaggingResult)
            structured = structured_llm.invoke([
                ("system", system_prompt),
                ("user", _clinical_prompt(docs)),
            ])
    except Exception as exc:
        trace.warn(COMPONENT, f"Clinical tagging agent failed ({exc}); falling back to direct structured prompt.")
        try:
            structured_llm = llm._chat.with_structured_output(ClinicalTaggingResult)
            structured = structured_llm.invoke([
                ("system", system_prompt),
                ("user", _clinical_prompt(docs)),
            ])
        except Exception as inner_exc:
            trace.warn(COMPONENT, f"Fallback direct prompt failed ({inner_exc}); retaining existing tags.")
            return docs

    if structured is None:
        trace.warn(COMPONENT, "Clinical agent returned no structured output; tags unchanged.")
        return docs
    if isinstance(structured, dict):
        structured = ClinicalTaggingResult.model_validate(structured)
    return enrich_documents_with_clinical_tags(docs, structured, policy, trace)


