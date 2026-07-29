"""ConsistencyAgent: tool-calling agent for soft cross-document checks.

True agent (`create_agent`) chooses which consistency tools to run. Required
checks that the agent skips are executed in code afterward (reliability rail).
Nothing here hard-rejects a claim — warnings only. Without an LLM, runs the
deterministic tool suite directly (no planner loop) for eval stability.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.contracts.documents import ExtractedDocument
from app.contracts.inputs import ClaimInput
from app.llm.client import LlmClient
from app.llm.prompts import CLINICAL_CONSISTENCY_PROMPT, NAME_RECONCILIATION_PROMPT
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.textnorm import normalize

COMPONENT = "ConsistencyAgent"

# How far apart a document date and the claimed treatment date may be before
# we flag it. Small gaps happen (report issued next day); big ones are odd.
DATE_TOLERANCE_DAYS = 3

SYSTEM_PROMPT = """You are a claims consistency specialist.
Run soft consistency checks across documents and the claim form.

Rules:
- Call EVERY check_* tool at least once (patient names, dates, amounts, provider,
  prescription requirement, clinical consistency).
- Use reconcile_name_with_llm only when check_patient_names reports mismatches.
- Warnings only — never approve/reject money or invent policy outcomes.
- Be concise in tool usage; do not repeat the same check unnecessarily.
"""

REQUIRED_TOOLS = (
    "check_patient_names",
    "check_document_dates",
    "check_amount_vs_bills",
    "check_provider_consistency",
    "check_prescription_requirement",
    "check_clinical_consistency",
)


class LlmNameVerdict(BaseModel):
    """Structured output for name reconciliation: are these the same person?"""

    same_person: bool
    rationale: str = Field(default="")


class LlmClinicalVerdict(BaseModel):
    """Structured output for medical necessity and clinical consistency."""

    consistent: bool
    rationale: str = Field(default="")


class ConsistencyAgentResult(BaseModel):
    summary: str = Field(default="Consistency checks completed.")


def _build_tools(
    claim: ClaimInput,
    member_name: str,
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None,
    store: dict[str, Any],
) -> list:
    warnings: list[str] = store["warnings"]
    called: set[str] = store["tools_called"]
    rules = policy.category_rules(claim.claim_category)

    @tool
    def check_patient_names() -> str:
        """Compare extracted patient names to the member roster name."""
        called.add("check_patient_names")
        doc_names = [d.patient_name for d in docs if d.patient_name]
        if not doc_names:
            msg = "No patient name could be extracted from any document."
            warnings.append(msg)
            trace.warn(COMPONENT, msg)
            store["mismatched_names"] = []
            return f"WARN: {msg}"
        member_norm = normalize(member_name)
        mismatched = [n for n in doc_names if normalize(n) != member_norm]
        store["mismatched_names"] = mismatched
        if not mismatched:
            trace.check(
                COMPONENT, True, f"Patient name '{member_name}' consistent across documents."
            )
            return f"OK: all names match member '{member_name}'."
        return (
            f"MISMATCH: {mismatched} vs member '{member_name}'. "
            "Call reconcile_name_with_llm for each mismatched name."
        )

    @tool
    def reconcile_name_with_llm(doc_name: str) -> str:
        """LLM second opinion: is doc_name the same person as the member? Clears soft mismatch only."""
        called.add("reconcile_name_with_llm")
        if llm is None:
            return "No LLM — cannot reconcile; mismatch stands."
        verdict = llm.structured(
            LlmNameVerdict,
            NAME_RECONCILIATION_PROMPT.format(member_name=member_name, doc_name=doc_name),
        )
        if verdict.same_person:
            store.setdefault("reconciled_names", set()).add(doc_name)
            trace.check(
                COMPONENT,
                True,
                f"Name variant '{doc_name}' reconciled with member '{member_name}' (LLM).",
            )
            return f"OK: '{doc_name}' reconciled as same person."
        return f"NOT_SAME: '{doc_name}' — {verdict.rationale or 'LLM does not confirm match'}."

    @tool
    def check_document_dates() -> str:
        """Flag document dates far from the claimed treatment date."""
        called.add("check_document_dates")
        flagged = 0
        for d in docs:
            if d.document_date is None:
                continue
            gap = abs((d.document_date - claim.treatment_date).days)
            if gap > DATE_TOLERANCE_DAYS:
                msg = (
                    f"{d.file_id} is dated {d.document_date.isoformat()}, {gap} days from "
                    f"the claimed treatment date {claim.treatment_date.isoformat()}."
                )
                warnings.append(msg)
                trace.warn(COMPONENT, msg)
                flagged += 1
        trace.check(COMPONENT, True, "Document dates checked against treatment date.")
        return f"OK: date check done ({flagged} warning(s))."

    @tool
    def check_amount_vs_bills() -> str:
        """Compare claimed amount to bill totals."""
        called.add("check_amount_vs_bills")
        bill_totals = [d.total_amount for d in docs if d.total_amount is not None]
        if not bill_totals:
            return "OK: no bill totals to compare."
        billed = sum(bill_totals)
        if abs(billed - claim.claimed_amount) > 1:
            msg = (
                f"Claimed amount ₹{claim.claimed_amount:,.0f} differs from the total "
                f"on the bill(s) ₹{billed:,.0f}."
            )
            warnings.append(msg)
            trace.warn(COMPONENT, msg)
            return f"WARN: {msg}"
        trace.check(COMPONENT, True, f"Claimed amount matches bill total (₹{billed:,.0f}).")
        return f"OK: claimed amount matches ₹{billed:,.0f}."

    @tool
    def check_provider_consistency() -> str:
        """Compare hospital on the claim form to providers on documents."""
        called.add("check_provider_consistency")
        doc_providers = [d.provider_name for d in docs if d.provider_name]
        if not (claim.hospital_name and doc_providers):
            return "OK: provider check skipped (missing form or document provider)."
        form_provider = normalize(claim.hospital_name)
        if any(
            form_provider in normalize(p) or normalize(p) in form_provider
            for p in doc_providers
        ):
            return "OK: form hospital matches document provider(s)."
        msg = (
            f"Provider mismatch: the claim form says '{claim.hospital_name}' but "
            f"the document(s) are from "
            + ", ".join(f"'{p}'" for p in doc_providers)
            + "."
        )
        warnings.append(msg)
        trace.warn(COMPONENT, msg)
        return f"WARN: {msg}"

    @tool
    def check_prescription_requirement() -> str:
        """If the category requires a prescription, verify one was extracted."""
        called.add("check_prescription_requirement")
        if not rules.requires_prescription:
            return "OK: category does not require a prescription."
        has_rx = any(d.doc_type.value == "PRESCRIPTION" for d in docs)
        trace.check(
            COMPONENT,
            has_rx,
            "Prescription present."
            if has_rx
            else "Category requires a prescription but none was extracted.",
        )
        if not has_rx:
            msg = "Required prescription is missing from extracted documents."
            warnings.append(msg)
            return f"WARN: {msg}"
        return "OK: prescription present."

    @tool
    def check_clinical_consistency() -> str:
        """Optional LLM check that treatment/meds align with diagnosis."""
        called.add("check_clinical_consistency")
        if llm is None:
            return "OK: clinical consistency skipped (no LLM)."
        diagnoses = [d.diagnosis for d in docs if d.diagnosis]
        treatments = [d.treatment for d in docs if d.treatment]
        medicines = [m for d in docs for m in d.medicines]
        tests = [t for d in docs for t in d.tests_ordered]
        if not diagnoses or not (treatments or medicines or tests):
            return "OK: insufficient clinical text for consistency check."
        try:
            verdict = llm.structured(
                LlmClinicalVerdict,
                CLINICAL_CONSISTENCY_PROMPT.format(
                    diagnosis=", ".join(diagnoses),
                    treatment=", ".join(treatments) or "(none listed)",
                    medicines=", ".join(medicines) or "(none listed)",
                    tests=", ".join(tests) or "(none listed)",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            trace.warn(
                COMPONENT, f"Clinical consistency evaluation skipped ({type(exc).__name__})."
            )
            return f"WARN: clinical check failed ({type(exc).__name__})."
        if verdict.consistent:
            trace.check(
                COMPONENT, True, "Clinical consistency verified: treatment aligns with diagnosis."
            )
            return "OK: clinically consistent."
        msg = f"Clinical inconsistency noted: {verdict.rationale}"
        warnings.append(msg)
        trace.warn(COMPONENT, msg)
        return f"WARN: {msg}"

    return [
        check_patient_names,
        reconcile_name_with_llm,
        check_document_dates,
        check_amount_vs_bills,
        check_provider_consistency,
        check_prescription_requirement,
        check_clinical_consistency,
    ]


def _apply_name_warnings(store: dict[str, Any], member_name: str, warnings: list[str]) -> None:
    mismatched = store.get("mismatched_names") or []
    if not mismatched:
        return
    reconciled = store.get("reconciled_names") or set()
    unreconciled = [n for n in mismatched if n not in reconciled]
    if unreconciled:
        msg = (
            f"Extracted patient name(s) {unreconciled} do not match member '{member_name}'."
        )
        if msg not in warnings:
            warnings.append(msg)


def _run_missing_tools(tools: list, called: set[str], trace: TraceRecorder) -> None:
    by_name = {t.name: t for t in tools}
    for name in REQUIRED_TOOLS:
        if name in called:
            continue
        trace.warn(COMPONENT, f"Agent skipped {name} — running deterministically.")
        tool_fn = by_name[name]
        # StructuredTool: invoke with empty args
        tool_fn.invoke({})


def run_consistency_agent(
    claim: ClaimInput,
    member_name: str,
    docs: list[ExtractedDocument],
    policy: Policy,
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> list[str]:
    """Run consistency checks via tool-calling agent (or direct tools if no chat model)."""
    store: dict[str, Any] = {
        "warnings": [],
        "tools_called": set(),
        "mismatched_names": [],
        "reconciled_names": set(),
    }
    tools = _build_tools(claim, member_name, docs, policy, trace, llm, store)
    by_name = {t.name: t for t in tools}

    def _run_tool_suite(*, reconcile: bool) -> list[str]:
        for name in REQUIRED_TOOLS:
            by_name[name].invoke({})
        if reconcile and llm is not None:
            for doc_name in list(store.get("mismatched_names") or []):
                by_name["reconcile_name_with_llm"].invoke({"doc_name": doc_name})
        _apply_name_warnings(store, member_name, store["warnings"])
        return store["warnings"]

    # No chat model (evals / unit fakes): run tools directly — still use llm.structured
    # inside reconcile/clinical tools when a FakeLlm provides it.
    if llm is None or getattr(llm, "_chat", None) is None:
        trace.skipped(
            COMPONENT,
            "No chat model — ConsistencyAgent running check tools directly.",
        )
        return _run_tool_suite(reconcile=llm is not None)

    agent = create_agent(
        model=llm._chat,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        response_format=ConsistencyAgentResult,
        name="consistency_agent",
    )
    agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Run full consistency checks for member '{member_name}', "
                        f"category {claim.claim_category.value}, "
                        f"claimed ₹{claim.claimed_amount:,.0f}, "
                        f"{len(docs)} document(s)."
                    ),
                }
            ]
        },
        config={
            "run_name": "consistency_agent",
            "tags": ["consistency", "agent"],
            "metadata": {"member_id": claim.member_id},
            "recursion_limit": 20,
        },
    )

    _run_missing_tools(tools, store["tools_called"], trace)
    # If names mismatched and agent never reconciled, try reconcile once per name.
    for doc_name in list(store.get("mismatched_names") or []):
        if doc_name not in (store.get("reconciled_names") or set()):
            if "reconcile_name_with_llm" not in store["tools_called"]:
                by_name["reconcile_name_with_llm"].invoke({"doc_name": doc_name})
    _apply_name_warnings(store, member_name, store["warnings"])
    return store["warnings"]
