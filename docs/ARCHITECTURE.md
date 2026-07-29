# Architecture — Health Insurance Claims Processing System

## Guiding principle: LLMs for perception, code for judgment

| Kind of work | Owner |
|---|---|
| **Perception** — documents, clinical tags, soft consistency | Three tool-calling agents (Gemini 3.6 Flash) |
| **Control** — order, early stop, HITL, parallel fan-out | LangGraph Claims Orchestrator |
| **Judgment** — waiting periods, co-pays, limits, decision | Deterministic Python from `policy_terms.json` |

## Multi-agent orchestrator architecture

```
                             Claims Orchestrator (LangGraph)
                                           │
         LangGraph Send (Parallel Fan-Out × N Uploads)
                                           ▼
            ┌─────────────────────────────────────────────────────────┐
            │ [document_worker × N]                                   │
            │ 🤖 DocumentPerceptionAgent (tool-calling, Gemini Vision)│
            └─────────────────────────────────────────────────────────┘
                                           │
                                           ▼
                                [verify_document_set]
                             (Document Verification Gate)
                                           │
                            issues? ───────┴─────── pass?
                               │                      │
                               ▼                      ▼
                      [DOCUMENT_REJECTED]     PARALLEL SUPER-STEP
                                              ┌───────┴───────┐
                                              ▼               ▼
                   ┌─────────────────────────────┐  ┌─────────────────────────────┐
                   │ [clinical_tagging]          │  │ [cross_validate]            │
                   │ 🤖 ClinicalAgent            │  │ 🤖 ConsistencyAgent         │
                   └─────────────────────────────┘  └─────────────────────────────┘
                                              └───────┬───────┘
                                                      ▼
                                                 [adjudicate]
                                         (Deterministic Policy Engine)
                                                      │
                                                      ▼
                                                 [fraud_check]
                                                      │
                                                      ▼
                                             [synthesize_decision]
                                                      │
                                                      ▼
                                              [human_review_gate]
                                         (LangGraph interrupt Pause)
```

### The three tool-calling agents

1. **DocumentPerceptionAgent** (`create_agent`) — per upload, parallel via `Send` fan-out  
   Tools: `vision_read_document` (≤1×), `apply_simulation_metadata`, `finalize_extraction`, `validate_extraction`.  
   Performs multi-modal vision OCR with Gemini 3.6 Flash to classify document types, assess quality, and extract itemized JSON fields.  
   No LLM → deterministic read/extract (evals). Attached with LangGraph `RetryPolicy(max_attempts=2)`.

2. **ClinicalAgent** (`create_agent`) — maps clinical text $\rightarrow$ policy tags  
   Tools: `lookup_policy_exclusion`, `check_condition_waiting_period`, `verify_high_value_test`, `list_waiting_condition_keys`.  
   Runs in parallel alongside `ConsistencyAgent`. Output whitelist-validated against `policy_terms.json`; **never decides money**. Skipped without LLM. Attached with `RetryPolicy(max_attempts=2)`.

3. **ConsistencyAgent** (`create_agent`) — soft cross-checks  
   Tools: `check_patient_names`, `reconcile_name_with_llm`, `check_document_dates`, `check_amount_vs_bills`, `check_provider_consistency`, `check_prescription_requirement`, `check_clinical_consistency`.  
   Runs in parallel alongside `ClinicalAgent`. Cross-checks patient roster names, bill totals, dates, and provider details. Warnings only—never approves or rejects money. Attached with `RetryPolicy(max_attempts=2)`.

### What is not an agent (on purpose)

| Piece | Role |
|---|---|
| **Document Gate** | Hard early stop with actionable member messages |
| **Policy Adjudicator** | Deterministic rules / amounts from `policy_terms.json` |
| **Fraud / Synthesizer** | Velocity signals + decision precedence |
| **Orchestrator** | Enforces pipeline flow, parallel fan-out, branch parallelization, HITL |

### Considered and rejected

- **Single ReAct agent that approves payouts** — fails explainability, evals, and early document stop.
- **Deep Agents / todo supervisors** — overkill latency/complexity for one claim.
- **Multiple vision tool hops per file** — burns Gemini calls; one `vision_read_document` max.

## Runtime registry

Non-serializable process objects (`policy`, `llm`, `TraceRecorder`, and upload bytes) live in `app.graph.runtime` keyed by `claim_id` rather than checkpointed graph state. This keeps base64 payload out of LangGraph state and LangSmith spans.

## Observability

LangSmith `plum-claims`: `ProcessClaim` parent run $\rightarrow$ `ClaimsGraph` $\rightarrow$ parallel node spans $\rightarrow$ agent/tool/`GeminiStructured` spans.

## Streaming & HITL

- `POST /claims/stream` streams NDJSON stage events live as nodes finish.
- When `CLAIMS_HITL=true` and a claim is flagged `MANUAL_REVIEW`, `human_review_gate` calls `interrupt()`.
- Resume via `POST /claims/{claim_id}/resume` with `action: "approve" | "reject"`.

## Scaling to 10× Volume

- **Parallelization**: Document workers fan out in parallel via `Send`, and `ClinicalAgent` + `ConsistencyAgent` run in a parallel super-step (30–40% latency reduction).
- **Checkpointer**: Swap `MemorySaver` $\rightarrow$ `PostgresSaver` for multi-replica state persistence across container clusters.
- **Retry Policies**: Attached native `RetryPolicy` on all LLM nodes for transient HTTP 429 / 503 resilience.
