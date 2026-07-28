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

## One vision read per document (2N → N LLM calls)

Real uploads are read exactly ONCE: the DocumentVerificationAgent's vision
call returns a single structured output (`LlmDocumentRead`) covering
classification (type, quality), extraction (fields, line items), and policy
tags. The raw read is stashed in graph state; the ExtractionAgent shapes it
into an `ExtractedDocument` without a second call. A 2-document claim costs
2 LLM calls, not 4; the stages stay logically separate — verification still
judges document sufficiency, extraction still owns the structured record.

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

## Observability: the trace is a first-class artifact

Every component appends `TraceEvent{sequence, component, event_type, status,
summary, detail}` as it works. The trace is returned in the API response,
rendered in the UI as an auditable table, and embedded in the eval report.
Design rules that keep it honest:

- **SKIPPED is recorded, not omitted.** When a check short-circuits or a
  component fails, the trace says so — a reader can distinguish "passed" from
  "never evaluated."
- **Details are structured.** `detail` carries rule inputs/outputs (limits,
  amounts, dates), so the trace is machine-queryable, not just prose.
- **Failures are trace events too.** `ComponentFailure` records which
  component, the error, the fallback, and the confidence penalty applied.

## Graceful degradation (TC011)

Every LLM-touching or parse-heavy node runs inside `run_resilient`: on
exception it (1) records a `ComponentFailure` in the trace, (2) executes a
safe fallback so the pipeline continues, (3) applies a confidence penalty.
The pipeline cannot 500 because a component timed out. The degraded state is
visible in the response (`degraded: true`, `component_failures[]`, a note
recommending manual review) and in the reduced confidence score (0.73 vs 0.98
for the same claim).

## Confidence: computed, never self-assessed

`confidence = 0.98 × mean(extraction confidences) × Π(1 − failure penalties)
× Π(data-quality penalties)`. Every factor is visible in the trace. LLMs are
never asked "how confident are you?" — the score is a transparent function of
observable facts: how well extraction went, whether any component failed,
whether key fields were readable.

## Dual-mode extraction (why)

The assignment's test cases provide documents two ways: metadata only
(TC001–TC003, targeting verification) and pre-extracted content (TC004–TC012,
targeting adjudication). Real uploads arrive as images/PDFs. Rather than
force one path, the ExtractionAgent accepts both: **provided-content mode**
keeps the eval suite deterministic and fast (no LLM calls, reproducible CI),
while **vision mode** handles real uploads in the UI. Same schema, same
downstream code, zero special-casing in adjudication.

## Live progress streaming

`POST /claims/stream` replays the SAME pipeline via
`graph.stream(stream_mode="updates")`, emitting one NDJSON event per node
(`{"type":"stage","stage","label","status","summary"}`) and a final
`{"type":"result","response"}` event whose payload is identical to
`POST /claims` (asserted byte-equal in tests). Each stage summary quotes the
actual trace line the node just produced — the progress UI is the pipeline
narrating itself, never a simulated stepper. The frontend reads the stream
over the same POST with a fetch reader and renders a six-stage checklist;
if the stream cannot be opened it falls back to the plain POST. Early
document rejection simply ends the stream after stage 1.

## Key interpretation decisions (documented assumptions)

1. **Per-claim limit scope.** The policy has both a blanket `per_claim_limit`
   (₹5,000) and category sub-limits that exceed it (dental ₹10,000, diagnostic
   ₹10,000). These conflict literally. Reading: the per-claim limit governs
   CONSULTATION (general OPD) claims; specialized categories are bounded by
   their own sub-limits. TC006 (dental ₹12,000 → PARTIAL ₹8,000, not rejected)
   vs TC008 (consultation ₹7,500 → REJECTED) pin this interpretation.
2. **Consultation sub-limit scope.** Applies to the consultation-fee portion
   of a claim, not bundled items (tests, medicines) — TC004/TC010 pin the
   math (₹1,500 → ₹1,350 with the full amount co-paid, not capped at ₹2,000
   first... the consultation portion is under the limit in both cases).
3. **Exclusions short-circuit.** An excluded condition is never payable, so
   when one matches, remaining hard checks are recorded SKIPPED (TC012).
4. **Network discount before co-pay.** Contractual ordering, pinned by TC010:
   ₹4,500 → ₹3,600 (20% discount) → ₹3,240 (10% co-pay).
5. **Hernia vs herniation.** Word-boundary matching: "lumbar disc herniation"
   (TC007) must not trigger the hernia waiting period; "chronic joint pain"
   (TC011) must not trigger joint replacement.

## What was considered and rejected

| Alternative | Why rejected |
|---|---|
| **LLM end-to-end adjudication** (feed docs + policy to one big prompt) | Unaccountable math, unexplainable decisions, non-deterministic — fails the observability and reliability requirements by construction. |
| **CrewAI / AutoGen multi-agent chat** | These frameworks optimize for emergent agent-to-agent conversation. Our problem is a structured pipeline with deterministic handoffs; chatty agents add cost, latency, and unpredictability with zero benefit. |
| **Deep Agents** | Built for open-ended, tool-using autonomous agents with filesystem access. Wrong shape for a deterministic adjudication pipeline. |
| **Vercel hosting** | Can't run a persistent Python service; would have forced the pipeline into less-mature LangGraph.js. Cloud Run runs any container, so the backend stays in Python where LangGraph and the document-AI ecosystem are strongest. |
| **Database (Postgres) now** | The assignment requires processing, not persistence. Stateless design removes a whole failure class and deploys trivially. Documented below how it enters at 10x. |
| **LLM-written explanations** | A paraphrase can drift from the actual trace. Explanations are rendered deterministically from trace events. |

## Limitations, and the 10x design

Current limitations, honestly:

1. **Stateless = no history.** Claim history in the UI is browser-local; the
   fraud agent consumes caller-supplied history. Fine for a demo, wrong for
   production.
2. **Synchronous processing.** A claim with 5 documents makes 5 sequential
   LLM calls inside one HTTP request (~10–20s with vision). The progress
   stream keeps the member informed meanwhile; true async is below.
3. **Single-region, min-instances 0.** First request after idle pays a cold
   start (~5–10s).
4. **Extraction is per-document sequential.** Parallelizable today.
5. **Deterministic matching is alias-based.** Novel phrasings beyond the
   alias tables are caught only in vision mode (LLM recall); simulation mode
   has no semantic net. Alias tables are curated, not learned.

At 10x load (750k claims/year ≈ 2k/day, bursts much higher):

- **Queue-based async intake.** API accepts the claim, writes to Postgres,
  enqueues to Cloud Tasks/Pub/Sub; workers process with per-claim
  idempotency keys. Members see "processing" then a notification; ops get a
  review queue. This also gives natural retry semantics for component
  failures (retry with backoff instead of instant fallback).
- **Postgres for claims + traces.** The trace model is already structured
  JSON — it maps directly to tables/JSONB. Fraud velocity checks become SQL
  over real history instead of caller input.
- **Parallel extraction.** Documents are independent — fan out with
  `asyncio.gather` or one task per document; 5-doc claim latency drops from
  sum to max.
- **Document storage in GCS** with signed upload URLs (browser → GCS direct),
  so the API never proxies multi-MB files.
- **Min-instances ≥ 1 + concurrency tuning** on Cloud Run; LLM provider
  rate-limit handling with token-bucket backoff.
- **Semantic layer for medical text.** The hybrid tagger (LLM recall +
  deterministic floor) is in place; at scale, add embedding similarity +
  a curated synonym store feeding the SAME tag contracts, evaluated against
  a labeled set. The deterministic layer stays as the high-precision floor.
- **Human review console.** MANUAL_REVIEW decisions already carry structured
  signals; at scale this becomes a first-class queue UI, and reviewer
  outcomes feed back as labeled data.

## Repository map

```
plum-claims/
├── backend/
│   ├── app/
│   │   ├── contracts/      # Pydantic schemas = component contracts
│   │   ├── policy/         # Policy loader (single source of truth)
│   │   ├── rules/          # Deterministic: adjudication, financial, fraud,
│   │   │                   #   waiting periods, tagging (semantic matching)
│   │   ├── agents/         # LLM-facing: verification (single read),
│   │   │                   #   extraction, cross-validation; + decision,
│   │   │                   #   explanation
│   │   ├── graph/          # LangGraph state + pipeline topology
│   │   ├── observability/  # Trace recorder, confidence model, resilience
│   │   ├── llm/            # Gemini client (the only model-touching module)
│   │   ├── service.py      # Application boundary (used by API and evals)
│   │   └── main.py         # FastAPI app
│   ├── tests/              # pytest — 48 tests, real policy, no mocks
│   ├── evals/run_evals.py  # 12-case eval → docs/EVAL_REPORT.md
│   └── data/               # policy_terms.json, test_cases.json
├── frontend/               # Next.js 15: form, live progress checklist,
│                           #   decision card, trace viewer
├── scripts/                # Mock document generator (demo assets)
└── docs/                   # This file, CONTRACTS.md, EVAL_REPORT.md
```
