# Demo Video Script (8–12 minutes)

Three required segments + intro/outro. Timings are targets.

---

## 0. Intro (0:00–0:45)

- "This is an AI claims-processing system for health insurance. A member
  uploads medical documents; the system verifies them, extracts data with a
  vision model, and adjudicates against the policy — with a full audit trace."
- Show the live URL and the repo layout for ~10 seconds.
- One sentence on the core principle: **"LLMs for perception, code for
  judgment — Gemini reads documents, but every rupee and every rule is
  deterministic Python driven by policy_terms.json."**

## 1. Segment A — Early stop on a document problem (0:45–3:00)

**Scenario:** TC001 — member uploads two prescriptions for a CONSULTATION
claim that requires a prescription + hospital bill.

1. Open the UI, select EMP001 (Rajesh Kumar), CONSULTATION, ₹1,500.
2. Upload `prescription_rajesh.jpg` **twice** (rename one copy
   `another_prescription.jpg`) — or describe the pre-baked scenario while
   running it via the eval harness.
3. Submit. **Show the error messages**, and read one aloud:
   - *"'another_prescription.jpg' is a prescription, but we still need your
     hospital bill. Please upload the correct document."*
4. Point out: no claim decision was made (status DOCUMENT_REJECTED), the
   message names the uploaded type AND the required type, and the trace shows
   exactly where processing stopped.
5. Optional 30s variant: upload `blurry_bill.jpg` for a PHARMACY claim to
   show the UNREADABLE_DOCUMENT path — "the claim is NOT rejected; we ask for
   a re-upload of that specific file."

## 2. Segment B — Successful end-to-end approval with full trace (3:00–7:30)

**Scenario:** TC004-style clean consultation — upload the two generated
mock documents (`prescription_rajesh.jpg`, `bill_rajesh.jpg`), EMP001,
CONSULTATION, 2024-11-01, ₹1,500.

1. Submit. Narrate while it processes (~15–20s, 4 LLM calls): "right now a
   vision model is classifying each document, then extracting structured
   fields, then the deterministic engine takes over."
2. On the decision card, walk through:
   - APPROVED, ₹1,350 of ₹1,500, confidence 0.98.
   - Financial breakdown: 10% co-pay = ₹150 deducted.
3. **Scroll the trace slowly** — this is the money shot. Call out:
   - DocumentVerificationAgent: both files classified with types + confidence.
   - ExtractionAgent: what was pulled from each document.
   - CrossValidationAgent: patient name consistent, amounts match.
   - AdjudicationEngine: each rule — member validity, waiting periods,
     exclusions, pre-auth, per-claim limit — with PASS status.
   - FraudAgent: no signals.
   - DecisionSynthesizer: decision + computed confidence.
4. Open the "Full explanation" details panel: "an ops engineer can
   reconstruct this entire decision from this trace alone — nothing is a
   black box."
5. Optional 45s variant: TC010-style network claim — same flow with
   hospital "Apollo Hospitals", ₹4,500 → show the adjustment table proving
   **discount before co-pay**: 4,500 → 3,600 → 3,240.

## 3. Segment C — Engineering pride + what I'd change (7:30–10:30)

**Proud of — the resilience/confidence contract (show TC011 live):**
1. Submit the alternative-medicine claim with "Simulate a component failure"
   checked.
2. Show: the decision still completes (APPROVED ₹4,000), but the degraded
   banner appears, the trace contains an explicit ERROR event naming the
   failed component and its fallback, confidence drops 0.98 → 0.73, and a
   note recommends manual review.
3. "Every component runs inside a resilience wrapper — a failure is recorded,
   a fallback runs, confidence pays a transparent penalty. The system can't
   500 because an LLM timed out. And confidence is **computed** from
   observable factors — never an LLM grading its own homework."

**Would change with more time (pick one, be honest):**
- "Exclusion and condition matching is alias-based today — high precision on
  phrasings I anticipated, but medical language is long-tailed. I built the
  hook for an LLM semantic second pass with policy citation; with more time
  I'd add embedding-based matching with a labeled eval set, keeping the
  deterministic pass as the high-precision first stage."
- (Also acceptable: async queue-based processing instead of synchronous
  request/response, per the 10x section of ARCHITECTURE.md.)

## 4. Outro (10:30–11:00)

- "Everything you saw is reproducible: `docker compose up` locally, 20 unit
  tests, 12/12 eval cases in docs/EVAL_REPORT.md, deployed on Cloud Run."
- Show the eval report table (12/12 PASS) for 5 seconds. Done.

---

### Pre-flight checklist for recording

- [ ] `docker compose up` OR live URL loaded and warm (hit it once before recording)
- [ ] `scripts/generate_mock_docs.py` run; 3 JPEGs ready to upload
- [ ] A copy of `prescription_rajesh.jpg` renamed `another_prescription.jpg` for Segment A
- [ ] Browser zoomed to ~125% for readability
- [ ] Eval report open in a tab for the outro
