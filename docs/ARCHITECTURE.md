# Architecture — Health Insurance Claims Processing System

## Guiding principle: LLMs for perception, code for judgment

| Kind of work | Owner |
|---|---|
| **Perception** — documents, clinical tags, soft consistency | Three tool-calling agents (Gemini) |
| **Control** — order, early stop, HITL, fan-out | LangGraph Claims Orchestrator |
| **Judgment** — waiting periods, co-pays, limits, decision | Deterministic Python from `policy_terms.json` |

## Multi-agent architecture

```
                 Claims Orchestrator (LangGraph)
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
 DocumentPerceptionAgent  ClinicalAgent     ConsistencyAgent
 (tool-calling, ×N Send)  (tool-calling)    (tool-calling)
         │                    │                    │
         └─────────┬──────────┴────────────────────┘
                   ▼
         Document Gate (rules) ── fail → DOCUMENT_REJECTED
                   │ pass
                   ▼
         Policy Adjudicator → Fraud → Synthesizer → HITL?
```

### The three real agents

1. **DocumentPerceptionAgent** (`create_agent`) — per upload, parallel via `Send`  
   Tools: `vision_read_document` (≤1×), `apply_simulation_metadata`, `finalize_extraction`, `validate_extraction`  
   No LLM → deterministic read/extract (evals).

2. **ClinicalAgent** (`create_agent`) — maps clinical text → policy tags  
   Tools: exclusion / waiting-period / high-value-test lookups  
   Output whitelist-validated; **never decides money**. Skipped without LLM.

3. **ConsistencyAgent** (`create_agent`) — soft cross-checks  
   Tools: names, dates, amounts, provider, prescription, clinical consistency (+ optional name LLM)  
   Required tools skipped by the model are **re-run in code**. Warnings only.

### What is not an agent (on purpose)

| Piece | Role |
|---|---|
| **Document Gate** | Hard early stop with actionable member messages |
| **Policy Adjudicator** | Deterministic rules / amounts from `policy_terms.json` |
| **Fraud / Synthesizer** | Signals + decision precedence |
| **Orchestrator** | Enforces pipeline, parallel fan-out, HITL |

### Considered and rejected

- **Single ReAct agent that approves payouts** — fails explainability, evals, and early document stop.  
- **Deep Agents / todo supervisors** — overkill latency/complexity for one claim.  
- **Multiple vision tool hops per file** — burns Gemini calls; one `vision_read_document` max.

## Runtime registry

`policy`, `llm`, `TraceRecorder`, and upload bytes live in `app.graph.runtime` (not checkpointed graph state).

## Observability

LangSmith `plum-claims`: `ProcessClaim` → `ClaimsGraph` → nodes → agent/tool/`GeminiStructured` spans.

## Streaming & HITL

`POST /claims/stream` NDJSON stages. `CLAIMS_HITL=true` + `MANUAL_REVIEW` → `interrupt()`; resume via API/UI.

## Scale (10×)

- Doc agents already parallel (`Send`).  
- Swap `MemorySaver` → `PostgresSaver` for multi-replica HITL.  
- Add specialists behind the orchestrator without touching adjudication.
