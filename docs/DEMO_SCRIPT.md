# Demo Video Script (8–12 minutes)

Assignment requires **exactly three beats**. Everything else is optional color.
Timings are targets — stay tight; prefer clear narration over more scenarios.

| Beat | Time | What reviewers must see |
|------|------|-------------------------|
| **A** | ~2 min | Document problem → early stop → **specific** error message |
| **B** | ~4–5 min | Clean approval end-to-end → **full audit trace** visible |
| **C** | ~3 min | One decision you’re **proud of** + one you’d **change** with more time |

Live UI: https://claims-ui-968299856642.asia-south1.run.app  
API health: https://claims-api-968299856642.asia-south1.run.app/health  
Design line to repeat: **“LLMs for perception, code for judgment.”**

---

## 0. Intro (0:00–0:45)

> *“Hi — this is Plum’s AI claims processing system. Members upload medical documents; we verify them early, extract with Gemini vision, then decide APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW against `policy_terms.json`. Vision and tagging are LLM perception. Waiting periods, co-pays, and limits are deterministic Python — never the model.”*

- Open the live UI (or localhost:3000).
- Optional one-liner: show `/health` → `llm_configured: true`.

---

## 1. Beat A — Early stop on a document problem (0:45–2:45)

**Goal:** Prove requirement #2 — stop before adjudication, with a member-actionable message.

**Scenario (TC001):** CONSULTATION needs a hospital bill; member uploads two prescriptions.

1. Fill the form:
   - Member: **EMP001 — Rajesh Kumar**
   - Category: **CONSULTATION**
   - Treatment date: **2024-11-01**
   - Claimed amount: **1500**
   - Documents: `prescription_rajesh.jpg` **twice** (rename one copy to `another_prescription.jpg` so both filenames show in the error)

2. Click **Submit claim**. Watch the live checklist — processing should stop after document read/verify (no full adjudication path).

3. On camera, read the status **`DOCUMENT_REJECTED`** and the exact issue text, e.g.:
   > *`[MISSING_DOCUMENT]` … consultation claim requires a hospital bill, but you uploaded … (PRESCRIPTION) … Please upload your hospital bill …*

4. Call out three things in one breath:
   - Message names **what was uploaded** and **what to upload next** (not a generic failure).
   - **`decision` is empty** — we never paid or rejected the claim on policy rules.
   - Trace shows the pipeline **halted at document verification**, before money rules ran.

**Optional 20s (only if time):** swap in `blurry_bill.jpg` → `UNREADABLE_DOCUMENT` (“re-upload a clearer photo”) — still early stop, still actionable.

---

## 2. Beat B — Successful end-to-end approval + full trace (2:45–7:30)

**Goal:** Prove requirements #3–#5 — extract, decide, explain.

**Scenario (clean consultation / TC004-style):** EMP001, CONSULTATION, ₹1,500, documents `prescription_rajesh.jpg` + `bill_rajesh.jpg`.

1. **Submit and show live progress** (NDJSON stream → checklist):
   - Reading documents → Verifying document set → Clinical policy tagging → Cross-checking details → Applying policy rules → Fraud screening → Finalizing decision → Human review  
   - One line: *“Each checkbox is a real LangGraph node finishing — not a fake spinner.”*

2. **Decision card — say the numbers out loud:**
   - Outcome: **`APPROVED`**
   - **₹1,350** of **₹1,500** (10% co-pay → ₹150 member share)
   - Point at **LLM call count** (vision reads + optional polish) — perception cost is visible, judgment is code
   - Read the **member message**; note the safety rail: polished prose is rejected if any ₹ / % / date from the template is missing

3. **Scroll the audit trace slowly** (this is the money shot for Observability):
   Walk 5–6 concrete lines, not every event:
   1. Documents classified (PRESCRIPTION + HOSPITAL_BILL) with confidence / quality  
   2. Extraction: diagnosis, line items, amounts  
   3. Clinical tagging / cross-check: roster name match (and any soft warnings)  
   4. Adjudication checks: waiting period, exclusions, sub-limits, co-pay — all **PASS** with reasons  
   5. Fraud: no velocity signals  
   6. Synthesizer: **APPROVED**, confidence score, approved amount  

   Closing line for this beat:
   > *“Ops can reconstruct this claim from the trace alone — no black box.”*

**Optional 30s (only if ahead of time):** set hospital to **Apollo Hospitals**, amount **4500** — show network discount **before** co-pay in the adjustments list (TC010 ordering).

**Optional 30s:** flip to LangSmith project `plum-claims`, open this run’s **`ProcessClaim`** tree (graph nodes → `GeminiStructured` / `ClinicalTaggingAgent`). Nice for Observability weight — not a substitute for the in-UI trace.

---

## 3. Beat C — Proud of / would change (7:30–11:00)

### Proud of — show it, don’t only talk about it

**Pick one (recommended: graceful degradation — assignment requirement #6):**

1. Same clean claim form; check **“Simulate a component failure”**; submit.
2. Show on screen:
   - Still **`DECIDED` / APPROVED** (or decided outcome) — **no 500**
   - **Degraded** flag / warning in the response
   - **Confidence drops** vs the clean run
   - Trace records the component failure + fallback used
3. Narrate:
   > *“I’m proud that confidence comes from observable failures and document quality — not an LLM grading itself. If cross-validation dies, we continue with what we have and tell ops the run was degraded.”*

**Alternate pride line (if you prefer architecture over the fault-injection demo):**
> *“Proud of the hard split: Gemini and the clinical tool-calling agent only tag and extract; every rupee and waiting-period date is pure Python on `policy_terms.json`. That keeps evals deterministic and decisions explainable.”*

### Would change given more time — one concrete next step

Be honest about what already exists (don’t promise work you’ve already shipped):

> *“HITL already pauses `MANUAL_REVIEW` with LangGraph `interrupt()` when `CLAIMS_HITL` is on, but the checkpointer is in-memory. At 10× load across multiple Cloud Run replicas I’d swap in `PostgresSaver` so a paused claim can resume on any instance, and add a reflection retry when extraction confidence is low before we ask the member to re-upload.”*

Do **not** say you’d “add parallel document workers” — **`Send` fan-out is already live.**

---

## 4. Outro (11:00–11:30)

> *“Reproducibility: **63 unit tests**, **12/12** assignment evals in `docs/EVAL_REPORT.md`. Code on GitHub with Docker Compose and Cloud Run. Thanks.”*

Flash `docs/EVAL_REPORT.md` or a terminal `pytest` / eval summary if it fits in 15 seconds.

---

## Pre-flight checklist

- [ ] UI loaded (Cloud Run or `docker compose up`) — cold start may take ~5–10s on first request
- [ ] Mock docs ready (`scripts/generate_mock_docs.py` → `scripts/mock_docs/`):
  - [ ] `prescription_rajesh.jpg`
  - [ ] `another_prescription.jpg` (copy of prescription for Beat A)
  - [ ] `bill_rajesh.jpg`
  - [ ] Optional: `blurry_bill.jpg`
- [ ] Browser zoom ~120%; mic check; hide bookmarks bar
- [ ] Tabs ready: UI | (optional) LangSmith `plum-claims` | EVAL_REPORT or terminal
- [ ] Practice Beat A error message once so you can read it without scrolling mid-sentence
- [ ] Know your Beat C “proud” demo (fault-injection checkbox) and the exact “would change” sentence above

---

## Timing guardrails

| If you’re over time | Cut first |
|---------------------|-----------|
| > 12 min | Optional blurry doc, Apollo network variant, LangSmith tab |
| Still long | Shorten Beat B trace to **four** events |
| Under 8 min | Add Apollo network ordering **or** 20s LangSmith tree |

**Do not skip:** specific document error (A), approval numbers + scrolled trace (B), on-camera proud demo + one change (C).
