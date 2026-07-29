# Component Contracts

Every significant component, its inputs, outputs, and error modes — precise
enough to reimplement any component without reading its code. The Pydantic
schemas in `backend/app/contracts/` are the machine-readable source of truth;
this document is the human-readable companion.

Conventions:

- "Raises" lists errors a component may *produce*. Any component marked
  **resilient** is wrapped by the pipeline in `run_resilient`, which converts
  any raise into a `ComponentFailure` trace record + fallback result.
- All money is INR float; all dates ISO `YYYY-MM-DD`; confidence ∈ [0, 1].

---

## 1. DocumentPerceptionAgent (tool-calling)

**File:** `app/agents/document_perception_agent.py` · **Resilient:** yes (fallback → UNREADABLE shell)

| | |
|---|---|
| **Input** | `doc: DocumentInput`; `claim: ClaimInput`; `policy: Policy`; `trace`; `llm: LlmClient \| None` |
| **Output** | `(ClassifiedDocument, ExtractedDocument \| None)` |
| **Raises** | Vision path may raise if LLM fails (caught by `run_resilient`) |

**Tools (when chat model present):** `vision_read_document` (≤1×), `apply_simulation_metadata`, `finalize_extraction`, `validate_extraction`.

**No chat model (evals):** deterministic `read_document` + `extract_one_document` (no planner loop).

Never decides coverage or money.

---

## 1b. Document Gate (`evaluate_document_set`)

**File:** `app/agents/document_verification.py` · **Not an agent** — hard early stop

| | |
|---|---|
| **Input** | `category`, `member_name`, `classified[]`, `policy`, `trace` |
| **Output** | `list[DocumentIssue]` — non-empty ⇒ `DOCUMENT_REJECTED` |

Issues: `UNREADABLE_DOCUMENT`, `MISSING_DOCUMENT`, `WRONG_DOCUMENT_TYPE`, `PATIENT_MISMATCH` — messages must name what was found and what to do next.

---

## 2. Extraction helpers

**File:** `app/agents/extraction.py` — used by DocumentPerceptionAgent `finalize_extraction` tool (and eval path). Shapes vision/simulation reads into `ExtractedDocument` + deterministic/LLM tag merge. Never assesses coverage.

---

## 3. ConsistencyAgent (tool-calling)

**File:** `app/agents/consistency_agent.py` · **Resilient:** yes · **Fault-injection point**

| | |
|---|---|
| **Input** | `claim`, `member_name`, `docs[]`, `policy`, `trace`, `llm` |
| **Output** | `list[str]` soft warnings |
| **Raises** | `RuntimeError` when `simulate_component_failure` (by design, in the graph node) |

**Tools:** `check_patient_names`, `reconcile_name_with_llm`, `check_document_dates`, `check_amount_vs_bills`, `check_provider_consistency`, `reconcile_provider_with_llm`, `check_prescription_requirement`, `check_clinical_consistency`.

Required tools skipped by the planner are re-run in code. Warnings only — never hard-stop.

Wrapper: `cross_validate()` in `consistency_agent.py` (alias for `run_consistency_agent`).

---

## 3b. ClinicalTaggingAgent

**File:** `app/agents/clinical_agent.py` · **Resilient:** yes (fallback → keep existing tags)

| | |
|---|---|
| **Input** | `docs: list[ExtractedDocument]`; `policy: Policy`; `llm: LlmClient \| None` |
| **Output** | `list[ExtractedDocument]` with tags union-merged from agent findings |
| **Raises** | LLM/tool failures (caught by `run_resilient`) |

Behavior contract:

1. If `llm is None` → no-op; deterministic tags retained (eval path).
2. Otherwise runs `langchain.agents.create_agent` with tools
   `lookup_policy_exclusion`, `check_condition_waiting_period`,
   `verify_high_value_test`, `list_waiting_condition_keys`.
3. Structured output `ClinicalTaggingResult` is whitelist-validated against
   the policy vocabulary, then union-merged into each document's tags.
4. Never calculates money, dates, or final decisions — perception only.

---

## 3c. HumanReviewGate (HITL)

**File:** `app/graph/pipeline.py` (`human_review_gate_node`) · Requires checkpointer

| | |
|---|---|
| **Input** | Graph state after synthesize; `hitl_enabled: bool` |
| **Output** | Updated `ClaimDecision` after ops resume, or no-op |
| **API** | Pause → `status=AWAITING_HUMAN_REVIEW`; resume via `POST /claims/{id}/resume` |

When `CLAIMS_HITL=true` and decision is `MANUAL_REVIEW`, calls LangGraph
`interrupt(payload)`. Resume body: `{action: "approve"|"reject", note?}`.
Approve pays `adjudication.approved_amount`; reject zeros the claim.
Evals keep `CLAIMS_HITL=false` so TC009 returns finished `MANUAL_REVIEW`.

---

## 4. AdjudicationEngine

**File:** `app/rules/adjudication.py` · **Resilient:** no (pure deterministic code; if it throws, that is a bug, not a degradation)

| | |
|---|---|
| **Input** | `claim: ClaimInput`; `policy: Policy`; `docs: list[ExtractedDocument]` |
| **Output** | `AdjudicationResult{checks[], rejection_reasons[], eligible_amount, approved_amount, line_items[], adjustments[]}` |
| **Raises** | `ValueError` only for unknown claim category (invalid policy config) |

Rule order (each appends a trace event; hard-fails short-circuit, later hard
checks recorded SKIPPED):

1. `MEMBER_NOT_FOUND` — member must be on the policy roster.
2. `SUBMISSION_DEADLINE_MISSED` — only if `submission_date` provided, else NOT_EVALUATED.
3. `BELOW_MINIMUM_AMOUNT` — claimed ≥ policy minimum.
4. `WAITING_PERIOD` (initial) — treatment ≥ join + initial days.
5. `EXCLUDED_CONDITION` — deterministic alias match of diagnosis/treatment
   against policy exclusions; **short-circuits everything**.
6. `WAITING_PERIOD` (specific) — matched conditions vs policy-specific days;
   reason MUST state the eligible-from date.
7. `PRE_AUTH_MISSING` — category requires pre-auth, or a high-value test above
   the category threshold, with no `pre_auth_reference`.
8. `PER_CLAIM_EXCEEDED` — CONSULTATION claims only (see ARCHITECTURE.md
   interpretation notes).
9. Line-item adjudication — dental/vision items matched against policy
   covered/excluded procedure lists; each rejected item carries a reason.
10. Financial computation — sub-limit cap → network discount → co-pay, in
    that order; each step emits an `Adjustment{kind, before, after, note}`.

Rejection reason codes: `MEMBER_NOT_FOUND`, `SUBMISSION_DEADLINE_MISSED`,
`BELOW_MINIMUM_AMOUNT`, `WAITING_PERIOD`, `EXCLUDED_CONDITION`,
`PRE_AUTH_MISSING`, `PER_CLAIM_EXCEEDED`, `NO_ELIGIBLE_LINE_ITEMS`.

---

## 5. FraudAgent

**File:** `app/rules/fraud.py` · **Resilient:** no (deterministic)

| | |
|---|---|
| **Input** | `member_id`; `treatment_date`; `claimed_amount`; `claims_history: list[PriorClaim]`; `thresholds: dict` (from policy) |
| **Output** | `FraudAssessment{fraud_score ∈ [0,1], signals: list[FraudSignal], requires_manual_review: bool}` |
| **Raises** | — |

Signals: `SAME_DAY_VELOCITY` (severity 0.70), `MONTHLY_VELOCITY` (0.40),
`HIGH_VALUE_CLAIM` (0.30); score = sum capped at 1.0. Manual review when any
velocity limit is breached, amount ≥ `auto_manual_review_above`, or score ≥
policy threshold. Signal descriptions MUST enumerate the specific prior
claims that triggered them.

---

## 6. DecisionSynthesizer

**File:** `app/agents/decision.py` · **Resilient:** no (deterministic)

| | |
|---|---|
| **Input** | `claimed_amount`; `adjudication: AdjudicationResult`; `fraud: FraudAssessment`; `confidence: float`; `failures: list[ComponentFailure]`; `cross_validation_warnings: list[str]` |
| **Output** | `ClaimDecision` (see contract schema) |
| **Raises** | — |

Precedence (first match wins): adjudication hard-fail → `REJECTED` (approved
0); fraud requires review → `MANUAL_REVIEW` (approved 0); any rejected line
item → `PARTIAL`; else `APPROVED`. Adds manual-review advisory notes when
degraded or when an approval's confidence < 0.80.

---

## 7. ConfidenceModel

**File:** `app/observability/confidence.py`

| | |
|---|---|
| **Input** | `docs: list[ExtractedDocument]`; `failures: list[ComponentFailure]` |
| **Output** | `float ∈ [0, 1]`, rounded to 2dp |

Formula: `0.98 × mean(doc.overall_confidence) × Π(1 − failure.penalty) ×
0.90^(# bills missing totals)`. Never uses LLM self-assessment.

---

## 8. Resilience wrapper

**File:** `app/observability/resilience.py`

`run_resilient(component, fn, fallback, trace, penalty=0.25, fallback_description) -> T`

Runs `fn()`; on ANY exception: appends a `ComponentFailure` (component,
error, fallback description, penalty) to the trace and returns `fallback()`.
Guarantee: the pipeline never propagates a component exception to the API.

---

## 9. ExplanationBuilder & MemberMessagePolisher

**Files:** `app/agents/explanation.py`, `app/agents/member_message.py`

Post-graph assembly in `ClaimService` — not LangGraph nodes.

| Component | Input | Output | Behavior |
|---|---|---|---|
| `build_explanation` | `ClaimResponse` | `str` (ops narrative) | Pure deterministic templating from trace events — no LLM. |
| `polish_member_message` | `template: str`, `llm`, `trace` | `str` (warm prose) | Optional LLM prose pass. Every figure in the template (amounts, dates, %) MUST be preserved verbatim in the rewrite; otherwise falls back to template. Disabled in evals/tests via `CLAIMS_POLISH_MESSAGES=false`. |

---

## 10. HTTP API

**File:** `app/main.py`

| Endpoint | Input | Output | Errors |
|---|---|---|---|
| `POST /claims` | `ClaimInput` JSON | `ClaimResponse` (200 always for processable claims, including REJECTED/DOCUMENT_REJECTED) | 422 on schema validation failure (malformed input) |
| `POST /claims/stream` | `ClaimInput` JSON | NDJSON (`application/x-ndjson`): one `{"type":"stage","stage","label","status","summary"?}` event per pipeline node, then a final `{"type":"result","response": ClaimResponse}` event. The result payload is identical to `POST /claims` | 422 as above |
| `GET /health` | — | `{status, llm_configured}` | — |

Note: a claim that is *rejected* is a successful 200 — rejection is a
business outcome, not an HTTP error. 4xx/5xx is reserved for malformed
requests and infrastructure failures.

Stream event details: the first event is always
`{"type":"stage","stage":"verify_documents","status":"running"}`; each node
then emits a `done` event (with `summary` quoting the node's last real trace
line) followed by the next node's `running` event. An early document
rejection ends the stream after `verify_documents` + the result event.

## 11. Semantic tagging (app/rules/tagging.py)

| | |
|---|---|
| `tag_deterministic(policy, *texts)` | `DocumentTags{conditions[], exclusions[]}` via word-boundary alias matching; aliases come from `policy_terms.json → matching_aliases`, pre-normalized by the loader |
| `validate_llm_tags(raw, policy)` | `(clean_tags, warnings)` — drops LLM tags that are not verbatim policy keys/entries |
| `merge_tags(llm, det, file_id)` | `TagMergeResult{tags, warnings}` — union; corroborated exclusions marked `via="both"`; asymmetric coverage → warnings |

`PolicyTag{entry, matched_text, via}` — `via ∈ deterministic | llm | both`.
`ExtractedDocument.tags` is `None` only when a document was built outside
the pipeline (adjudication then tags it deterministically on the spot).

---

## 12. LangSmith Observability (app/observability/langsmith.py)

| | |
|---|---|
| **Function** | `configure_langsmith()` |
| **Behavior** | If `LANGSMITH_API_KEY` (or `LANGCHAIN_API_KEY`) is set: exports tracing env vars and project `plum-claims`. |
| **Parent runs** | `@traceable ProcessClaim` wraps `ClaimService.process` and `process_stream`; `ResumeClaim` wraps HITL resume. Inputs strip base64; outputs summarize decision/status. |
| **Graph config** | `graph_config(...)` sets `thread_id`, `run_name`, tags (`plum-claims`, mode, `claim_id`), and metadata (member, category, amounts). |
| **Child spans** | LangGraph nodes auto-nest; `GeminiStructured` wraps vision/structured LLM calls (image bytes not uploaded); `ClinicalTaggingAgent` wraps the tool-calling agent. |
| **Annotate** | `annotate_claim_run(response)` stamps final decision/status/llm_calls onto the parent run. |
| **Side Effects** | Hierarchical traces appear under the `plum-claims` LangSmith project when a key is configured; otherwise no-op. |
