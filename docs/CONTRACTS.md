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

## 1. DocumentVerificationAgent

**File:** `app/agents/document_verification.py` · **Resilient:** yes (fallback → synthetic UNREADABLE issue)

| | |
|---|---|
| **Input** | `category: ClaimCategory`; `member_name: str`; `documents: list[DocumentInput]`; `policy: Policy`; `llm: LlmClient \| None` |
| **Output** | `(classified: list[ClassifiedDocument], issues: list[DocumentIssue])` — one `ClassifiedDocument` per input document, in order |
| **Raises** | `RuntimeError` if a document needs vision classification but no LLM client is configured |

Behavior contract:

1. Each document is classified into `detected_type ∈ DocumentType`,
   `quality ∈ {GOOD, LOW, UNREADABLE}`, optional `patient_name_on_doc`.
   Real files → vision model; simulation metadata → used directly.
2. Emits a `DocumentIssue` for each of:
   - `UNREADABLE_DOCUMENT` — quality UNREADABLE; message names the file and
     asks for a re-upload of that specific document; never rejects the claim.
   - `MISSING_DOCUMENT` — a type in policy `document_requirements[category].required`
     is absent; message names what was uploaded and what is required.
   - `WRONG_DOCUMENT_TYPE` — uploaded type not in required ∪ optional, or a
     surplus duplicate of an accepted type; message names found vs expected.
   - `PATIENT_MISMATCH` — documents name >1 distinct patient, or a single
     patient different from the claiming member; message names the names found.
3. Non-empty `issues` ⇒ the pipeline MUST stop before any claim decision
   (`status: DOCUMENT_REJECTED`).
4. Side effects: one trace event per classified document + one per issue.

---

## 2. ExtractionAgent

**File:** `app/agents/extraction.py` · **Resilient:** yes, per document (fallback → document excluded)

| | |
|---|---|
| **Input** | `documents: list[DocumentInput]`; `classified: list[ClassifiedDocument]`; `llm: LlmClient \| None` |
| **Output** | `list[ExtractedDocument]` (may be shorter than input if documents failed) |
| **Raises** | `RuntimeError` if vision extraction is needed but no LLM client is configured; LLM timeout/validation errors propagate to the resilience wrapper |

Behavior contract:

1. Mode selection per document: `file_content_base64` present → vision;
   `content` present → provided-content normalization; otherwise metadata-only
   shell with `overall_confidence = 0.5`.
2. Output fields mirror the source document: `patient_name`, `doctor_name`,
   `doctor_registration`, `provider_name`, `document_date`, `diagnosis`,
   `treatment`, `medicines[]`, `tests_ordered[]`, `line_items[]`,
   `total_amount`, `overall_confidence`, `unreadable_fields[]`.
3. Never invents values: illegible fields are null + listed in
   `unreadable_fields`, and `overall_confidence` drops proportionally.
4. Never assesses coverage, exclusions, or limits.

---

## 3. CrossValidationAgent

**File:** `app/agents/cross_validation.py` · **Resilient:** yes (fallback → skip + warning) · **Fault-injection point**

| | |
|---|---|
| **Input** | `claim: ClaimInput`; `member_name: str`; `docs: list[ExtractedDocument]`; `policy: Policy` |
| **Output** | `list[str]` — human-readable warnings (empty = all consistent) |
| **Raises** | nothing for data problems; `RuntimeError` when `claim.simulate_component_failure` is true (by design) |

Checks (warnings only, never hard-stops): patient name vs roster name;
document dates within 3 days of treatment date; claimed amount vs sum of
bill totals; prescription presence when the category requires one.

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

## 9. ExplanationBuilder

**File:** `app/agents/explanation.py`

| | |
|---|---|
| **Input** | `ClaimResponse` (fully populated except `explanation`) |
| **Output** | `str` — ops narrative: status line, issues/decision summary, financial breakdown, numbered trace |
| **Raises** | — |

Deterministic templating only; no LLM.

---

## 10. HTTP API

**File:** `app/main.py`

| Endpoint | Input | Output | Errors |
|---|---|---|---|
| `POST /claims` | `ClaimInput` JSON | `ClaimResponse` (200 always for processable claims, including REJECTED/DOCUMENT_REJECTED) | 422 on schema validation failure (malformed input) |
| `GET /health` | — | `{status, llm_configured}` | — |

Note: a claim that is *rejected* is a successful 200 — rejection is a
business outcome, not an HTTP error. 4xx/5xx is reserved for malformed
requests and infrastructure failures.
