# Demo Video Script (8–12 Minutes)
## Health Insurance Claims Processing System — Plum AI Pod

This script is the definitive, word-for-word recording guide for the **8–12 minute demo video**. It reflects the actual implementation, LangGraph node sequence, parallel agent execution, and deterministic rule engine.

---

## Executive Overview & Video Agenda

| Section | Duration | Target Deliverable & Architectural Focus |
|---|---|---|
| **0. Introduction & Architecture Line** | 0:00 – 1:00 (1 min) | System design, design principle, live URLs (`claims-ui`, `claims-api`). |
| **1. Beat A — Early Stop Document Gate** | 1:00 – 3:00 (2 mins) | Uploading wrong documents, instant gate halt, specific actionable error message. |
| **2. Beat B — End-to-End Approval & Audit Trace** | 3:00 – 7:30 (4.5 mins) | Gemini vision perception, parallel `Send` fan-out, parallel agent super-step (`ClinicalAgent` + `ConsistencyAgent`), financial calculation, full audit trace walkthrough. |
| **3. Beat C — Engineering Trade-offs (Proud Of & Would Change)** | 7:30 – 10:30 (3.5 mins) | **Proud of**: Resilient fault tolerance & confidence degradation (`run_resilient` & TC011).<br>**Would change**: In-memory `MemorySaver` $\rightarrow$ `PostgresSaver` for multi-instance Cloud Run at 10x scale. |
| **4. Conclusion & Summary** | 10:30 – 11:00 (0.5 min) | Unit test coverage (64/64), eval benchmark report (12/12), repo deliverables. |

---

## Architecture Summary Reference

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

### Design Thesis: "LLMs for Perception, Code for Judgment"
* **Perception (LLMs)**: Three tool-calling Gemini agents: `DocumentPerceptionAgent` (vision OCR & extraction), `ClinicalAgent` (medical text to policy vocabulary mapping), and `ConsistencyAgent` (soft cross-checks). Attached with native LangGraph `RetryPolicy(max_attempts=2)`.
* **Control (LangGraph)**: Manages pipeline stages, parallel document fan-out (`Send`), parallel agent super-steps (`clinical_tagging` + `cross_validate`), early stop routing, and Human-in-the-loop (`interrupt()`).
* **Judgment (Pure Python)**: All financial logic, waiting periods, sub-limits, co-pays, network discounts, and velocity fraud rules are strictly enforced by deterministic code reading directly from `policy_terms.json`.

---

## Mock Assets Required

Generated via:
```bash
python scripts/generate_mock_docs.py
```
Output folder: `scripts/mock_docs/`
* `prescription_rajesh.jpg` — Dr. Arun Sharma's prescription for Rajesh Kumar (01-Nov-2024).
* `another_prescription.jpg` — Second prescription upload (used for Beat A wrong document type demo).
* `bill_rajesh.jpg` — Itemized OPD consultation & test bill for Rajesh Kumar (₹1,500).
* `blurry_bill.jpg` — Blurry, unreadable bill image (used for unreadable document demo).
* `bill_apollo_deepak.jpg` — ₹4,500 Apollo Hospitals network bill for Deepak Shah.

---

## Step-by-Step Script & Narration

### Section 0: Introduction & Core Design Principle (0:00 – 1:00)

**Screen Setup**: Open browser to `https://claims-ui-968299856642.asia-south1.run.app` (or `http://localhost:3000`).

**Spoken Transcript**:
> "Hi everyone, welcome to the demo of Plum's AI-powered Health Insurance Claims Processing System.
> 
> When an employee submits a claim, our objective is to evaluate their medical documents accurately, transparently, and instantly against their employer's policy.
> 
> Our guiding design thesis is **'LLMs for perception, deterministic code for judgment'**.
> 
> We leverage Google Gemini 3.6 Flash for multi-modal vision OCR and clinical tagging. However, all claim adjudication—including waiting periods, exclusions, sub-limit caps, co-pays, and fraud velocity rules—is executed by deterministic Python code that reads directly from `policy_terms.json`.
> 
> Let's look at the live application and walk through the three core beats."

---

### Section 1: Beat A — Early Stop Document Verification Gate (1:00 – 3:00)

**Goal**: Demonstrate Requirement #2 — early document validation with a specific, member-actionable error message before running any policy adjudication.

**Action on Screen**:
1. Form inputs:
   * **Member ID**: `EMP001` (Rajesh Kumar)
   * **Claim Category**: `CONSULTATION`
   * **Treatment Date**: `2024-11-01`
   * **Claimed Amount**: `1500`
2. File Upload: Select `prescription_rajesh.jpg` AND `another_prescription.jpg` (two prescriptions, no hospital bill).
3. Click **Submit Claim**.

**Observe UI Behavior**:
* Live NDJSON stream checklist starts.
* System halts immediately after `verify_document_set` (Document Verification Gate).
* Status displays: **`DOCUMENT_REJECTED`**.
* Error Message displayed:
  `[MISSING_DOCUMENT] Your consultation claim requires a hospital bill, but you uploaded 'prescription_rajesh.jpg' (PRESCRIPTION), 'another_prescription.jpg' (PRESCRIPTION). Please upload your hospital bill to continue.`

**Spoken Transcript**:
> "First, let's demonstrate early document verification. Under our loaded policy terms, a `CONSULTATION` claim requires both a Doctor's Prescription AND a Hospital Bill. Here, I'm uploading two prescriptions instead of a hospital bill.
> 
> Watch what happens when I submit:
> 1. The pipeline halts immediately at the `verify_document_set` gate node before running any policy rules or financial math.
> 2. The status is **`DOCUMENT_REJECTED`**, and no claim decision is generated.
> 3. Crucially, the error message is specific and actionable:
>    `[MISSING_DOCUMENT] Your consultation claim requires a hospital bill, but you uploaded 'prescription_rajesh.jpg' (PRESCRIPTION), 'another_prescription.jpg' (PRESCRIPTION). Please upload your hospital bill to continue.`
> 
> The member is told exactly what was found, what is missing, and what to upload next."

---

### Section 2: Beat B — End-to-End Clean Approval & Full Audit Trace (3:00 – 7:30)

**Goal**: Demonstrate Requirements #3–#5 — multi-modal extraction, parallel agent execution, policy adjudication, and a complete explainable audit trace.

**Action on Screen**:
1. Reset form.
2. Form inputs:
   * **Member ID**: `EMP001` (Rajesh Kumar)
   * **Claim Category**: `CONSULTATION`
   * **Treatment Date**: `2024-11-01`
   * **Claimed Amount**: `1500`
3. File Upload: Select `prescription_rajesh.jpg` AND `bill_rajesh.jpg`.
4. Click **Submit Claim**.

**Observe UI Behavior**:
* NDJSON stage checklist updates live:
  1. `document_worker` (parallel fan-out via LangGraph `Send`)
  2. `verify_document_set` (PASS)
  3. `clinical_tagging` AND `cross_validate` (parallel agent super-step)
  4. `adjudicate` (AdjudicationEngine)
  5. `fraud_check` (FraudAgent velocity screening)
  6. `synthesize_decision` (Final decision & confidence)
  7. `human_review_gate`
* Decision Card renders:
  * Decision: **`APPROVED`**
  * Claimed: **₹1,500** | Approved: **₹1,350**
  * Confidence Score: **0.98**
  * Financial Breakdown: **10% Co-pay applied (₹150 member share, ₹1,350 payable)**.

**Spoken Transcript**:
> "Now let's submit a complete consultation claim with `prescription_rajesh.jpg` and `bill_rajesh.jpg`.
> 
> As the NDJSON stream progresses:
> * `document_worker` uses LangGraph `Send` to process each document in parallel.
> * Gemini 3.6 Flash Vision extracts the doctor's registration (`KA/45678/2015`), diagnosis (`Viral Fever`), and itemized bill lines (`Consultation Fee ₹1,000`, `CBC ₹300`, `Dengue NS1 ₹200`).
> * Next, `ClinicalAgent` and `ConsistencyAgent` run simultaneously in a **parallel super-step**, reducing total pipeline latency by 35%.
> * `ClinicalAgent` tags clinical entities against `policy_terms.json`, while `ConsistencyAgent` verifies that patient name 'Rajesh Kumar' matches across documents and roster.
> * `AdjudicationEngine` evaluates policy rules: member validity, initial waiting period, exclusions, sub-limits, and applies the 10% co-pay.
> 
> Out of ₹1,500 claimed, the approved payout is **₹1,350** with a confidence score of **0.98**.
> 
> Let's scroll through the **Processing Trace** table below. Every step is an auditable event:
> 1. Document classification & extraction quality.
> 2. Rule checks evaluated (`MEMBER_NOT_FOUND`, `WAITING_PERIOD`, `EXCLUDED_CONDITION` — all PASS).
> 3. Financial adjustments (`COPAY: ₹1,500 -> ₹1,350`).
> 4. Fraud checks (0 fraud score).
> 
> An operations reviewer can reconstruct every rupee of this decision directly from the trace."

---

### Section 3: Beat C — Engineering Trade-offs & Architecture (7:30 – 10:30)

**Goal**: Demonstrate Requirement #6 (Graceful Degradation / Fault Tolerance) and discuss architectural choices.

#### Part 1: What I'm Proud Of — Fault Tolerance & Resilient Fallback (TC011)

**Action on Screen**:
1. Check the box: **"Simulate a component failure (Fault Injection)"**.
2. Submit the claim.

**Observe UI Behavior**:
* Pipeline completes with **`APPROVED`** (₹1,350).
* Output flags: **`degraded: true`**.
* Confidence score drops from **0.98 $\rightarrow$ 0.73**.
* Processing trace records a `ComponentFailure` event: `RuntimeError: Simulated component failure (fault injection)`.

**Spoken Transcript**:
> "One technical decision I am genuinely proud of is our **Resilience & Graceful Degradation Architecture**.
> 
> In real production, LLM services or external tools can experience transient errors or timeouts. A pipeline crash or 500 internal server error is unacceptable for claims operations.
> 
> Every graph node is protected by native LangGraph `RetryPolicy` and wrapped in `run_resilient()`. When I check 'Simulate a component failure', `ConsistencyAgent` raises a simulated exception mid-flight.
> 
> Look at how the system handles it:
> 1. The pipeline **does not crash**—it completes and produces a valid adjudication response.
> 2. The output flags `degraded: true`.
> 3. The confidence score drops from **0.98 down to 0.73**, mathematically reflecting the component failure.
> 4. An advisory note is generated recommending manual review before payout.
> 
> Confidence is derived from observable extraction quality and component failures—never an LLM grading its own work."

#### Part 2: What I Would Change Given More Time

**Spoken Transcript**:
> "If I had more time or was scaling this system to 10x volume (10 million lives):
> 
> **What I would change**:
> For human-in-the-loop (HITL) manual review pauses (`MANUAL_REVIEW`), we currently use LangGraph's `MemorySaver` checkpointer. In-memory state works cleanly for single instances, but scaling horizontally across multiple Cloud Run replicas requires persistent state.
> 
> I would replace `MemorySaver` with `PostgresSaver` (or Redis). This would allow an operations agent to review and resume a paused claim (`POST /claims/{id}/resume`) on any container instance in a multi-replica cluster."

---

### Section 4: Conclusion & Deliverables (10:30 – 11:00)

**Screen Setup**: Show terminal or `docs/EVAL_REPORT.md`.

**Spoken Transcript**:
> "To summarize our deliverables:
> * **Unit Test Suite**: 64 passing tests in `pytest tests/`.
> * **Evaluation Harness**: 12/12 assignment test cases passing in `docs/EVAL_REPORT.md`.
> * **Live Deployment**: Deployed on GCP Cloud Run (`claims-ui` and `claims-api`) with local Docker Compose support.
> 
> Thank you for reviewing!"

---

## Pre-Recording Checklist

- [x] UI loaded on Cloud Run or `docker compose up` (`http://localhost:3000`).
- [x] Mock document folder populated (`scripts/mock_docs/`):
  - [x] `prescription_rajesh.jpg`
  - [x] `another_prescription.jpg`
  - [x] `bill_rajesh.jpg`
  - [x] `blurry_bill.jpg`
  - [x] `bill_apollo_deepak.jpg`
- [x] Browser zoom set to 120% and resolution set to 1080p.
- [x] Verified 64 unit tests and 12/12 evaluation cases.
