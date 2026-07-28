# Architecture — Health Insurance Claims Processing System

## Guiding principle: LLMs for perception, code for judgment

| Kind of work | Owner |
|---|---|
| **Perception** — document vision, name reconciliation, clinical tagging | Gemini 3.6 Flash + tool-calling agent |
| **Judgment** — waiting periods, co-pays, limits, decision precedence | Deterministic Python from `policy_terms.json` |

## LangGraph multi-agent pipeline

```
START ──Send──▶ document_worker × N   ← parallel read + extract
      │
verify_document_set ──issues?──▶ END (DOCUMENT_REJECTED)
      │
clinical_tagging     ← create_agent + policy tools (LLM only; skipped in evals)
      │
cross_validate       ← soft checks + fault injection (TC011)
      │
adjudicate           ← deterministic rules engine
      │
fraud_check
      │
synthesize_decision
      │
human_review_gate    ← interrupt() when MANUAL_REVIEW and CLAIMS_HITL=true
      │
     END
```

### What each agentic piece does

1. **Parallel document workers (`Send`)** — One worker per upload. Vision read + extraction run concurrently. Results merge via list/dict reducers. TraceRecorder is lock-guarded.
2. **ClinicalTaggingAgent (`langchain.agents.create_agent`)** — Real tool-calling agent with:
   - `lookup_policy_exclusion`
   - `check_condition_waiting_period`
   - `verify_high_value_test`
   - `list_waiting_condition_keys`  
   Output is structured tags, whitelist-validated, union-merged into document tags. **Never decides money.** Skipped when no LLM (evals use deterministic tags only).
3. **Human-in-the-loop** — When `CLAIMS_HITL=true` and the decision is `MANUAL_REVIEW`, `interrupt()` pauses the graph. Ops resumes via `POST /claims/{id}/resume` with `approve` or `reject`. Checkpointer: `MemorySaver` (demo); production would use `PostgresSaver`. Evals keep `CLAIMS_HITL=false` so TC009 still returns `MANUAL_REVIEW` as a finished decision.

### Runtime registry

`policy`, `llm`, and `TraceRecorder` are **not** stored in checkpointed graph state (they are not JSON-serializable). They live in `app.graph.runtime` keyed by `claim_id` (= LangGraph `thread_id`).

## Semantic tagging

Clinical free text → tags (conditions, exclusions) via:

1. Deterministic alias matcher (`policy_terms.json`) — eval / fallback path  
2. Vision LLM tags (single read) and/or ClinicalTaggingAgent — live path  
Union-merge; disagreements become trace warnings. Adjudication consumes tags only.

## Observability

LangSmith project `plum-claims`. Each claim is one parent run (`ProcessClaim` for
sync/stream, `ResumeClaim` for HITL) with nested `ClaimsGraph` → node spans,
`GeminiStructured` LLM calls, `clinical_tagging_agent` tool loops, and
`MemberMessagePolish`. Upload bytes stay in the runtime registry (not graph
state) so spans stay small. Parent outputs summarize the decision — stream
stage events are not dumped into the root run.

## Streaming

`POST /claims/stream` emits NDJSON: `stage` events, optional `interrupt`, then `result`.

## Scaling notes

- Parallel document fan-out already uses `Send`.
- Swap `MemorySaver` → `PostgresSaver` for durable HITL across replicas.
- Add reflection retry edge on low extraction confidence when needed.
