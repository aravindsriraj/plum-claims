# System Architecture & Technical Design Document
## Health Insurance Claims Processing System — Plum AI Pod

---

## 1. Executive Summary & Core Design Thesis

Processing employee health insurance claims requires balancing **intelligence** (reading messy handwritten prescriptions, blurry bills, and non-standard medical terms) with **100% precision and explainability** (calculating exact financial payouts, enforcing waiting periods, sub-limits, co-pays, and audit compliance).

To solve this, our system is built around a single core architectural thesis:

> **"LLMs for Perception, Deterministic Code for Judgment"**

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      1. UNSTRUCTURED INPUT DATA                        │
 │           (Medical Uploads: Prescriptions, Bills, Lab Reports)         │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                       2. PERCEPTION LAYER (AI)                         │
 │     Gemini 3.6 Flash Agents: OCR Vision + Semantic Medical Tagging     │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                       3. JUDGMENT LAYER (CODE)                         │
 │     Deterministic Python Rule Engine: Payouts, Co-pays, Waiting Dates   │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                     4. EXPLAINABLE CLAIM OUTCOME                       │
 │         Final Decision + Approved Amount + Complete Audit Trace        │
 └────────────────────────────────────────────────────────────────────────┘
```

### Why This Division of Responsibilities?
* **LLMs Excel at Perception**: Extracting OCR text from blurry photos, recognizing doctor signatures, mapping clinical terms (e.g., `"T2DM"` or `"high blood sugar"` $\rightarrow$ `"diabetes"`), and comparing Indian name variations.
* **LLMs Fail at Judgment**: LLMs are prone to floating-point arithmetic errors, overconfidence, hallucinated policy rules, and inconsistent decisions under complex constraint combinations.
* **Code Guarantees Precision**: All financial calculations, waiting period dates, sub-limits, co-pays, network hospital discounts, and velocity fraud checks are strictly executed by deterministic Python code reading directly from `policy_terms.json`. Zero financial logic is ever delegated to an LLM.

---

## 2. Multi-Agent Orchestrator Architecture

The overall claims pipeline is modeled as a stateful **LangGraph Claims Orchestrator** enforcing execution sequence, parallel fan-out, parallel super-steps, early gate halts, and human-in-the-loop pauses.

```
                             START (Claim Submission)
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ 1. Read Uploaded Documents (Parallel AI) │
                  │    - Vision OCR + Text Extraction        │
                  └─────────────────────┬────────────────────┘
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ 2. Document Verification Gate            │
                  │    - Checks Missing / Blurry / Wrong Docs│
                  └─────────────────────┬────────────────────┘
                                        │
                       ┌────────────────┴────────────────┐
                 (Has Issues)                       (Valid Docs)
                       │                                 │
                       ▼                                 ▼
             [ DOCUMENT REJECTED ]              PARALLEL AI STEP
           (Ask Member to Re-upload)      ┌──────────────┴──────────────┐
                                          ▼                             ▼
                              ┌──────────────────────┐      ┌──────────────────────┐
                              │ 3. Clinical AI Tagger│      │ 4. Consistency AI    │
                              │    (Diagnoses & Tags)│      │    (Name & Provider) │
                              └───────────┬──────────┘      └───────────┬──────────┘
                                          └──────────────┬──────────────┘
                                                         │
                                                         ▼
                              ┌────────────────────────────────────┐
                              │ 5. Policy Adjudication Engine      │
                              │    (Python Money Math & Limits)    │
                              └──────────────────┬─────────────────┘
                                                 │
                                                 ▼
                              ┌────────────────────────────────────┐
                              │ 6. Fraud Velocity Screening        │
                              │    (Check Repeat / High-Value)     │
                              └──────────────────┬─────────────────┘
                                                 │
                                                 ▼
                              ┌────────────────────────────────────┐
                              │ 7. Decision Synthesizer            │
                              │    (Calculate Confidence Score)    │
                              └──────────────────┬─────────────────┘
                                                 │
                                                 ▼
                              ┌────────────────────────────────────┐
                              │ 8. Operations Review Gate (HITL)   │
                              │    (Optional Human Pause / Resume) │
                              └──────────────────┬─────────────────┘
                                                 │
                                                END
```

---

## 3. Detailed Component Breakdown

### A. The Perception Layer (3 Tool-Calling Agents)

#### 1. DocumentPerceptionAgent (`backend/app/agents/document_perception_agent.py`)
* **Role**: Processes raw upload images or PDFs using **Google Gemini 3.6 Flash Vision**.
* **Parallel Execution**: Fanned out concurrently via LangGraph `Send` ($N$ workers for $N$ uploads).
* **Tools**: `vision_read_document`, `apply_simulation_metadata`, `finalize_extraction`, `validate_extraction`.
* **Output**: Returns document classification (`PRESCRIPTION`, `HOSPITAL_BILL`, `PHARMACY_BILL`, `LAB_REPORT`), quality assessment (`GOOD`, `LOW`, `UNREADABLE`), and structured JSON extraction (patient name, doctor registration `KA/45678/2015`, diagnosis, itemized line items, amounts).
* **Efficiency Constraint**: Strict ceiling of **$\le 1$ vision API call per file** to minimize latency and token cost. Attached with native LangGraph `RetryPolicy(max_attempts=2)`.

#### 2. ClinicalAgent (`backend/app/agents/clinical_agent.py`)
* **Role**: Maps free-text medical diagnosis, treatment, and test descriptions onto the policy vocabulary in `policy_terms.json`.
* **LLM-Powered Tools**: `lookup_policy_exclusion`, `check_condition_waiting_period`, `verify_high_value_test`, `list_waiting_condition_keys`. Under the hood, each tool executes a structured mini-LLM call (`with_structured_output`) to perform deep AI-driven semantic categorization of medical terms (e.g. `"T2DM"` -> `"diabetes"`, `"morbid obesity"` -> `"Obesity and weight loss programs"`).
* **Behavior**: ReAct tool-calling agent constructed via LangChain `create_agent`, running in a **parallel super-step** alongside `ConsistencyAgent`.
* **Safety Rail**: Outputs are whitelist-checked against `policy_terms.json`. Any tag not matching verbatim policy keys is automatically dropped and flagged. **Never calculates money or dates.**

#### 3. ConsistencyAgent (`backend/app/agents/consistency_agent.py`)
* **Role**: Performs cross-document reconciliation and entity consistency verification.
* **LLM-Powered Tools**: `check_patient_names`, `reconcile_name_with_llm`, `check_document_dates`, `check_amount_vs_bills`, `check_provider_consistency`, `reconcile_provider_with_llm`, `check_prescription_requirement`, `check_clinical_consistency`.
* **Behavior**: Uses dedicated LLM tools for name reconciliation (`reconcile_name_with_llm`) and hospital provider reconciliation (`reconcile_provider_with_llm`) to handle Indian naming conventions (e.g., `"R. Kumar"` vs `"Rajesh Kumar"`) and hospital branch/affiliate name variations (e.g., `"Apollo Clinic Indiranagar"` vs `"Apollo Hospitals"`).
* **Constraint**: Emits soft warnings into the trace—**never hard-rejects claims or alters financial figures.**

---

### B. The Judgment & Decision Layer (Pure Python)

#### 1. Document Verification Gate (`verify_document_set` node)
* **Hard Early Stop**: Evaluates classified documents before running policy rules.
* **Checks**:
  * Are required document types present for the category? (e.g., `CONSULTATION` requires `PRESCRIPTION` + `HOSPITAL_BILL`).
  * Is any document unreadable/blurry?
  * Do patient names belong to different individuals across uploads?
* **Outcome**: If invalid, halts immediately with status `DOCUMENT_REJECTED` and returns a **specific, member-actionable error message** telling the member what was found and what to upload next.

#### 2. AdjudicationEngine (`backend/app/rules/adjudication.py`)
Pure Python rule engine that reads `policy_terms.json` dynamically (zero hardcoded rules in code):
1. **Member Validity**: Checks if member ID exists on the policy roster.
2. **Submission Deadline**: Checks if treatment date is within allowed deadline days.
3. **Minimum Claim Amount**: Enforces minimum claim floor (₹500).
4. **Initial Waiting Period**: Checks 30-day blanket waiting period from join date.
5. **Policy Exclusions**: Checks primary diagnosis against excluded conditions (e.g., Obesity, Bariatric Surgery, Substance Abuse). Short-circuits claim if matched.
6. **Specific Waiting Periods**: Evaluates condition-specific waiting days (e.g., Diabetes 90 days, Hernia 180 days) and computes the exact `eligible_from` date.
7. **Pre-Authorization**: Enforces pre-auth reference checks for category rules or high-value diagnostics (e.g., MRI > ₹10,000).
8. **Per-Claim Limit**: Enforces per-claim limits (₹5,000 for consultation).
9. **Line-Item Adjudication**: Evaluates itemized procedure lines against covered vs excluded procedure lists (e.g., approving Root Canal ₹8,000, rejecting Teeth Whitening ₹4,000).
10. **Financial Calculation Chain**:
    $$\text{Eligible Amount} \longrightarrow \text{Category Sub-limit Cap} \longrightarrow \text{Network Hospital Discount} \longrightarrow \text{Co-pay Member Share}$$

#### 3. FraudAgent (`backend/app/rules/fraud.py`)
* Deterministic velocity screening against historical member submissions:
  * `SAME_DAY_VELOCITY`: $>2$ claims from the same member on the same day.
  * `MONTHLY_VELOCITY`: Exceeding monthly claim limits.
  * `HIGH_VALUE_CLAIM`: Claims crossing auto-review thresholds (₹25,000).
* Calculates a fraud risk score $\in [0, 1]$ and triggers `MANUAL_REVIEW` when breached.

#### 4. DecisionSynthesizer (`backend/app/judgment/decision.py`)
* Synthesizes outputs into terminal decisions (`APPROVED`, `PARTIAL`, `REJECTED`, `MANUAL_REVIEW`).
* Calculates mathematical confidence score.

---

## 4. Resilience, Reliability & Fault-Tolerance

### 1. 4-Tier Tiered Fault Handling
To prevent pipeline crashes, external API timeouts or tool failures are handled gracefully:

```
+-----------------------------------------------------------------------+
| TIER 1: LangGraph Native RetryPolicy                                  |
| Automatically retries transient HTTP 429 rate limits & 503 timeouts.   |
+-----------------------------------------------------------------------+
                                   | (If retries exhausted)
                                   v
+-----------------------------------------------------------------------+
| TIER 2: run_resilient() Fallback Wrapper                              |
| Catches node exceptions, logs ComponentFailure, returns safe defaults.|
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| TIER 3: Mathematical Confidence Erosion                               |
| Multiplicative confidence penalty applied (e.g. 0.98 -> 0.73).        |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| TIER 4: Human-in-the-Loop Gate (interrupt)                            |
| Claims with confidence < 0.80 or degraded state pause for review.     |
+-----------------------------------------------------------------------+
```

### 2. Transparent Mathematical Confidence Model
Confidence is **never an LLM self-assessment** (which is prone to overconfidence). It is calculated mathematically:

$$\text{Confidence} = 0.98 \times \left(\frac{1}{N} \sum_{i=1}^N \text{Doc Extraction Quality}_i\right) \times \prod (1 - \text{Failure Penalty}) \times \prod \text{Quality Penalties}$$

---

## 5. Human-in-the-Loop (HITL) Subsystem

When `CLAIMS_HITL=true` and a claim is flagged as `MANUAL_REVIEW`:
1. The `human_review_gate` node calls `interrupt(payload)`, pausing execution.
2. The claim status is returned as `AWAITING_HUMAN_REVIEW`.
3. Operations staff review the audit trace and submit `POST /claims/{claim_id}/resume`:
   ```json
   {
     "action": "approve",
     "note": "Pre-auth verified offline by ops agent"
   }
   ```
4. LangGraph resumes execution via `Command(resume=...)`, executing the approved payout.

---

## 6. Observability & Audit Trail

* **In-Memory Trace (`TraceRecorder`)**: Every event, check, financial adjustment, warning, and component failure is recorded in monotonic sequence and returned in the API `trace` array.
* **LangSmith Integration (`plum-claims`)**: Full hierarchical tracing:
  `ProcessClaim` (Parent Run) $\rightarrow$ `ClaimsGraph` (LangGraph) $\rightarrow$ Nodes $\rightarrow$ `GeminiStructured` (LLM Spans).

---

## 7. Scaling to 10x – 100x Volume

1. **Parallel Super-Steps**: Document workers fan out in parallel via `Send`, and `ClinicalAgent` + `ConsistencyAgent` execute concurrently (35%+ latency reduction).
2. **Stateless Graph Memory**: Upload images base64 bytes are stored in process-local `app.graph.runtime` rather than checkpointed graph state, keeping LangGraph state payloads $<10\text{ KB}$.
3. **Production Checkpointer (`PostgresSaver`)**: Replacing in-memory `MemorySaver` with `PostgresSaver` enables stateless Cloud Run / Kubernetes auto-scaling across container replicas.
4. **Asynchronous Task Queue**: Transitioning submissions to an async task queue (Cloud Tasks / PubSub) with WebSockets/SSE updates for high throughput.
