# Architecture — Health Insurance Claims Processing System

## The problem in one paragraph

A member uploads medical documents (bills, prescriptions, lab reports) plus claim
metadata. The system must (1) catch document problems before any processing,
(2) extract structured data from messy real-world documents, (3) decide
APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW against a JSON-defined policy,
(4) explain every decision completely, and (5) degrade gracefully when
components fail. This document explains how the system does that, what was
considered and rejected, and where the design breaks at 10x load.

---

## Guiding principle: LLMs for perception, code for judgment

The single most important architectural decision. The system's work divides
into two kinds:

| Kind of work | Examples | Owner |
|---|---|---|
| **Perception** (fuzzy, unstructured) | Is this photo a prescription or a bill? What does this Rx say? Does "high sugar" mean diabetes? Is "Magnetic Resonance Imaging" an MRI? Is "OPD visit" a consultation fee? Are "R. Kumar" and "Rajesh Kumar" the same person? Member-facing prose polishing. | LLM agents (Gemini 3.6 Flash) |
| **Judgment** (exact, accountable) | Waiting-period date math, co-pay calculation, sub-limits, what to DO with an exclusion or high-value test, per-claim limits, final decision precedence | Deterministic Python rules engine |

Anything that touches money, dates, or policy logic is **pure code driven by
`policy_terms.json`** — never an LLM output, never hardcoded. This is why the
system is reliable: an LLM can misread a document (and confidence drops
accordingly), but it cannot miscalculate a co-pay, because it never calculates
one. Every eval case that pins exact arithmetic (TC004 ₹1,350, TC010 ₹3,240)
is decided by table-driven, unit-tested pure functions.

---

## Agentic Architecture & ReAct Tool-Calling Sub-Agents

Rather than relying on a single monolithic prompt or an unbounded open-ended ReAct loop (which introduces financial hallucination risks and high latency), our system implements a **LangGraph Multi-Agent Architecture**:

```
                       ┌──────────────────────────────────────────┐
                       │          LANGGRAPH SUPERVISOR            │
                       └────────────────────┬─────────────────────┘
                                            │
   ┌───────────────────┬────────────────────┼────────────────────┬───────────────────┐
   ▼                   ▼                    ▼                    ▼                   ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ Verification  │  │ Extraction    │  │ Clinical      │  │ Adjudication  │  │ Communication │
│ Vision Agent  │  │ Parsing Agent │  │ ReAct Agent   │  │ Policy Agent  │  │ Prose Agent   │
│ Tools: OCR    │  │ Tools: Parser │  │ Tools: Policy │  │ Tools: Math   │  │ Tools: Regex  │
└───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘
```

### Specialized Sub-Agents

1. **ClinicalReasoningAgent (ReAct Sub-Agent):** An autonomous node in the graph that inspects clinical text and billing line items by dynamically invoking domain policy tools:
   - `lookup_policy_exclusion(term)` — Queries whitelist policy exclusion entries and alias dictionaries.
   - `check_condition_waiting_period(condition)` — Queries condition-specific waiting periods.
   - `verify_high_value_test_preauth(test_name, amount)` — Evaluates high-value imaging tests (MRI, CT, PET) against category pre-auth thresholds.
2. **CrossValidationAgent (Identity Reconciliation & Medical Necessity):**
   - Uses `LlmNameVerdict` to resolve Indian name variations ("R. Kumar" ~ "Rajesh Kumar") and eliminate false patient mismatch warnings.
   - Uses `LlmClinicalVerdict` to evaluate medical necessity (verifying that prescribed treatments/medicines align with the diagnosis).
3. **MemberMessagePolisher (Communication Agent):**
   - Takes the hardcoded decision summary and rewrites it in warm, empathetic prose.
   - **Safety Rail:** Enforces a Python regex check verifying that **all rupee amounts and figures survive verbatim**; falls back to the template if any figure is altered.

---

## Semantic tagging: how clinical text meets the policy

Mapping free-text diagnoses to policy concepts ("Type 2 Diabetes Mellitus" →
the `diabetes` waiting-period condition; "bariatric consultation" → an
exclusion) is perception — it lives OUTSIDE the rule engine. The flow:

```
clinical text ──▶ tags (conditions, exclusions, procedure matches)
                     │
        two independent producers, UNION-merged:
        1. deterministic matcher — word-boundary aliases from
           policy_terms.json (matching_aliases). Precision floor;
           the ONLY tagger in provided-content/eval mode.
        2. the vision LLM — returns tags in the same structured read;
           validated against the policy vocabulary (hallucinated
           entries dropped + flagged), adding recall for phrasings
           no alias anticipates.
                     │
        disagreements → trace warnings, never silently resolved
                     ▼
        AdjudicationEngine consumes tags only — set membership,
        never raw-text matching. Every tag records provenance
        (via: deterministic | llm | both) for the audit trail.
```

Two properties worth noting:

- **The vocabulary has ONE home.** Alias tables live in `policy_terms.json`,
  not in code — edit the JSON and both taggers change behavior together.
  The loader pre-normalizes aliases once; per-claim matching normalizes each
  document text once.
- **The LLM is never trusted blindly.** Its tags are whitelist-checked
  against actual policy entries before use; the deterministic matcher runs
  as an independent cross-check in vision mode, and as the sole tagger in
  eval mode — so evals exercise exactly the production fallback path.

---

## One vision read per document (2N → N LLM calls)

Real uploads are read exactly ONCE: the DocumentVerificationAgent's vision
call returns a single structured output (`LlmDocumentRead`) covering
classification (type, quality), extraction (fields, line items), and policy
tags. The raw read is stashed in graph state; the ExtractionAgent shapes it
into an `ExtractedDocument` without a second call. A 2-document claim costs
2 LLM calls, not 4; the stages stay logically separate — verification still
judges document sufficiency, extraction still owns the structured record.

---

## Observability: LangSmith Tracing & Audit Trail

The system is natively instrumented with **LangSmith Tracing** (`project: plum-claims`):
- Top-level claim processing is decorated with `@traceable(name="ProcessClaim", run_type="chain")`.
- Every LangGraph node (`verify_documents`, `extract_documents`, `cross_validate`, `clinical_reasoning`, `adjudicate`, `fraud_check`, `synthesize_decision`) produces nested spans in LangSmith.
- Tool calls and Gemini 3.6 Flash LLM invocations record token usage, input/output schemas, and latency metrics in real-time.

```
ProcessClaim (Root Chain)
 ├── verify_documents_node
 │    └── ChatGoogleGenerativeAI (Vision Read)
 ├── extract_documents_node
 ├── cross_validate_node
 │    └── ChatGoogleGenerativeAI (LlmNameVerdict / LlmClinicalVerdict)
 ├── clinical_reasoning_node (ReAct Sub-Agent)
 │    ├── lookup_policy_exclusion (@tool)
 │    ├── check_condition_waiting_period (@tool)
 │    └── verify_high_value_test_preauth (@tool)
 ├── adjudicate_node (Deterministic Engine)
 ├── fraud_check_node (Deterministic Engine)
 └── synthesize_decision_node
```

---

## Real-Time Progress Streaming (HTTP NDJSON)

To eliminate black-box loading states, the backend exposes `POST /claims/stream`:
1. As each LangGraph node finishes execution, it yields a newline-delimited JSON (`application/x-ndjson`) event: `{"type": "stage", "stage": "clinical_reasoning", "status": "done", "summary": "..."}`.
2. The Next.js frontend (`ProgressChecklist.tsx`) reads the chunked HTTP response via a fetch reader and updates the 7-stage checklist in real time.
3. The final event `{"type": "result", "response": ClaimResponse}` carries the complete claim payload.

---

## System overview

```
                         ┌──────────────────────────────────────────────┐
 Browser (Next.js UI)    │              Backend (FastAPI)               │
 ┌───────────────┐       │                                              │
 │ Claim form    │ POST  │  LangGraph pipeline (7 nodes):               │
 │ File upload   ├──────▶│                                              │
 │ Decision card │ /api  │  1 DocumentVerificationAgent ─┐ issues?      │
 │ Trace viewer  │◀──────┤  2 ExtractionAgent            ▼              │
 └───────────────┘       │  3 CrossValidationAgent   EARLY STOP         │
                         │  4 ClinicalReasoningAgent (ReAct tools)      │
                         │  5 AdjudicationEngine  (deterministic)       │
                         │  6 FraudAgent          (deterministic)       │
                         │  7 DecisionSynthesizer (deterministic)       │
                         └──────────────┬───────────────────────────────┘
                                        │ vision & reasoning calls
                                 ┌──────▼──────┐
                                 │ Gemini 3.6  │
                                 │ Flash       │
                                 └─────────────┘
```

Two deployable units (Cloud Run services), one repo:

- **`backend/`** — Python 3.12, FastAPI + LangGraph + Pydantic v2 + LangSmith tracing.
  Stateless: a claim goes in, a decision + full trace comes out in the same response.
- **`frontend/`** — Next.js 15 (TypeScript). Server-side rewrite proxies
  `/api/*` to the backend, rendering real-time 7-stage streaming progress via NDJSON.

---

## The pipeline (multi-agent, LangGraph)

```
verify_documents ──document issues?──▶ END (status: DOCUMENT_REJECTED)
      │ none
extract_documents            ← per-document resilience isolation
      │
cross_validate               ← designated fault-injection point (TC011) + name/clinical checks
      │
clinical_reasoning           ← ReAct sub-agent invoking policy tools (exclusion, waiting, pre-auth)
      │
adjudicate                   ← 10 ordered rule checks, all from policy JSON
      │
fraud_check                  ← velocity / value signals
      │
synthesize_decision ────────▶ END (status: DECIDED, decision + trace)
```

### Component responsibilities

1. **DocumentVerificationAgent** — Reads every upload ONCE via Gemini 3.6 Flash vision
   (classification + extraction + policy tags in a single structured output —
   see "One vision read per document"), or simulation metadata in eval mode.
   Validates the set against `document_requirements` in the policy.
   Any problem produces a specific, member-actionable issue ("'another_
   prescription.jpg' is a prescription, but we still need your hospital bill")
   and the pipeline stops *before any claim decision*. This is a hard
   assignment requirement (TC001–TC003) and 10% of the grade.

2. **ExtractionAgent** — Per document, produces a validated, tagged
   `ExtractedDocument` (patient, doctor + registration, diagnosis, line
   items, totals, per-field unreadable flags, semantic tags). Two input
   modes — vision (shaped from the verification read, LLM tags validated +
   merged) and provided-content (deterministically tagged) — converge on the
   same Pydantic schema, so downstream code can't tell them apart.
   Illegible fields are flagged, never guessed.

3. **CrossValidationAgent** — Consistency *across* documents: patient identity (with
   LLM name reconciliation via `LlmNameVerdict`), document dates vs treatment date,
   claimed amount vs bill totals, and LLM medical necessity evaluation (`LlmClinicalVerdict`).
   Warnings only; reduces confidence, never hard-stops. This is the designated fault-
   injection point: `simulate_component_failure` forces it to raise.

4. **ClinicalReasoningAgent (ReAct Sub-Agent)** — An autonomous ReAct node that evaluates
   clinical text and billing line items by dynamically invoking domain policy tools
   (`lookup_policy_exclusion`, `check_condition_waiting_period`, `verify_high_value_test_preauth`).
   Appends tool execution evidence directly to state and the trace.

5. **AdjudicationEngine** — Not an LLM agent. Ten ordered rule checks (member
   validity → submission deadline → minimum amount → initial waiting period →
   exclusions → specific waiting periods → pre-auth → per-claim limit →
   line-item adjudication → financial computation). Hard-fail checks
   short-circuit and record what was skipped. Every check appends a trace event.

6. **FraudAgent** — Deterministic velocity/value signals from
   `fraud_thresholds`: same-day claim velocity, monthly velocity, high-value
   claims. Produces a fraud score and a manual-review flag with the specific
   signals enumerated (TC009).

7. **DecisionSynthesizer** — Combines adjudication + fraud + computed
   confidence into the final decision with fixed precedence:
   hard-fail → REJECTED; fraud flag → MANUAL_REVIEW; some line items
   rejected → PARTIAL; else APPROVED.

8. **MemberMessagePolisher & ExplanationBuilder** — `MemberMessagePolisher` rewrites
   status messages in warm prose, validated by a regex check ensuring all figures survive
   verbatim. `ExplanationBuilder` renders the trace into an ops narrative by deterministic
   templating.

---

## Graceful degradation (TC011)

Every LLM-touching or parse-heavy node runs inside `run_resilient`: on
exception it (1) records a `ComponentFailure` in the trace, (2) executes a
safe fallback so the pipeline continues, (3) applies a confidence penalty.
The pipeline cannot 500 because a component timed out. The degraded state is
visible in the response (`degraded: true`, `component_failures[]`, a note
recommending manual review) and in the reduced confidence score (0.73 vs 0.98
for the same claim).

---

## Confidence: computed, never self-assessed

`confidence = 0.98 × mean(extraction confidences) × Π(1 − failure penalties)
× Π(data-quality penalties)`. Every factor is visible in the trace. LLMs are
never asked "how confident are you?" — the score is a transparent function of
observable facts: how well extraction went, whether any component failed,
and whether unreadable fields or date discrepancies were present.

---

## What was considered and rejected

1. **Unbounded ReAct Loop for Policy Evaluation:** Asking an open-ended LLM agent to calculate co-pays and policy limits introducing 1-3% calculation variance across runs.
   - *Chosen instead:* LangGraph Sub-Agents using deterministic `@tool` functions.
2. **Multiple LLM vision calls per document:** Running 1 call for classification, 1 for extraction, 1 for tagging (2N+ calls).
   - *Chosen instead:* Single vision read per upload (`LlmDocumentRead`) returning classification, extraction, and tagging in 1 call (N calls).
3. **LLM summaries for ops explanations:** Generative summaries can hallucinate or omit trace events.
   - *Chosen instead:* Deterministic trace rendering in `ExplanationBuilder`.

---

## Scaling to 10x Load (Operations & Throughput)

To scale from current volume to 10x throughput (750,000+ claims/year):
1. **Parallel Vision Fan-out with LangGraph `Send` API:** Use `Send` to process multi-document uploads in parallel worker nodes rather than sequential loops.
2. **Persistent Checkpointing (`PostgresSaver`):** Upgrade graph compilation from ephemeral state to PostgreSQL checkpointing to support async queue workers and resumable Human-in-the-Loop workflows.
3. **Model Caching & Batching:** Cache static policy embeddings and pre-normalized alias tables across requests.
