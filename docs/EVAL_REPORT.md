# Eval Report — 12 Test Cases

Generated: 2026-07-29T09:58:28  
Result: **12/12 passed** (deterministic run, no LLM calls — documents use provided-content/metadata modes)

| Case | Name | Expected | Actual | Result |
|------|------|----------|--------|--------|
| TC001 | Wrong Document Uploaded | EARLY_STOP | DOCUMENT_REJECTED | PASS |
| TC002 | Unreadable Document | EARLY_STOP | DOCUMENT_REJECTED | PASS |
| TC003 | Documents Belong to Different Patients | EARLY_STOP | DOCUMENT_REJECTED | PASS |
| TC004 | Clean Consultation — Full Approval | APPROVED | APPROVED | PASS |
| TC005 | Waiting Period — Diabetes | REJECTED | REJECTED | PASS |
| TC006 | Dental Partial Approval — Cosmetic Exclusion | PARTIAL | PARTIAL | PASS |
| TC007 | MRI Without Pre-Authorization | REJECTED | REJECTED | PASS |
| TC008 | Per-Claim Limit Exceeded | REJECTED | REJECTED | PASS |
| TC009 | Fraud Signal — Multiple Same-Day Claims | MANUAL_REVIEW | MANUAL_REVIEW | PASS |
| TC010 | Network Hospital — Discount Applied | APPROVED | APPROVED | PASS |
| TC011 | Component Failure — Graceful Degradation | APPROVED | APPROVED | PASS |
| TC012 | Excluded Treatment | REJECTED | REJECTED | PASS |

---

## TC001 — Wrong Document Uploaded

**Member submits two prescriptions for a consultation claim that requires a prescription and a hospital bill.**

- Status: `DOCUMENT_REJECTED`
- Member-facing issues:
  - [MISSING_DOCUMENT] Your consultation claim requires a hospital bill, but you uploaded 'dr_sharma_prescription.jpg' (PRESCRIPTION), 'another_prescription.jpg' (PRESCRIPTION). Please upload your hospital bill to continue.
  - [WRONG_DOCUMENT_TYPE] 'another_prescription.jpg' is a prescription, but we still need your hospital bill. Please upload the correct document.

<details><summary>Full trace</summary>

```
Claim CLM-F8886F93: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [MISSING_DOCUMENT] Your consultation claim requires a hospital bill, but you uploaded 'dr_sharma_prescription.jpg' (PRESCRIPTION), 'another_prescription.jpg' (PRESCRIPTION). Please upload your hospital bill to continue.
  [WRONG_DOCUMENT_TYPE] 'another_prescription.jpg' is a prescription, but we still need your hospital bill. Please upload the correct document.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: dr_sharma_prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F001: extracted via METADATA (confidence 0.50)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: another_prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F002: extracted via METADATA (confidence 0.50)
    8. [WARN] DocumentVerificationAgent: Required document HOSPITAL_BILL is missing from the upload.
    9. [WARN] DocumentVerificationAgent: F002: PRESCRIPTION does not satisfy the requirements.
```
</details>

## TC002 — Unreadable Document

**Member uploads a valid prescription but a blurry, unreadable photo of their pharmacy bill.**

- Status: `DOCUMENT_REJECTED`
- Member-facing issues:
  - [UNREADABLE_DOCUMENT] We couldn't read your pharmacy bill ('blurry_bill.jpg') — the image is too blurry or damaged. Please re-upload a clear photo of that same document. Your claim has NOT been rejected; it will continue once we can read this document.

<details><summary>Full trace</summary>

```
Claim CLM-5749AEF9: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [UNREADABLE_DOCUMENT] We couldn't read your pharmacy bill ('blurry_bill.jpg') — the image is too blurry or damaged. Please re-upload a clear photo of that same document. Your claim has NOT been rejected; it will continue once we can read this document.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: PHARMACY, ₹800, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F003: extracted via METADATA (confidence 0.50)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: blurry_bill.jpg: read as PHARMACY_BILL (quality UNREADABLE, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F004: extracted via METADATA (confidence 0.50)
    8. [WARN] DocumentVerificationAgent: F004: document unreadable, re-upload requested.
```
</details>

## TC003 — Documents Belong to Different Patients

**The prescription is for Rajesh Kumar but the hospital bill is for a different patient, Arjun Mehta.**

- Status: `DOCUMENT_REJECTED`
- Member-facing issues:
  - [PATIENT_MISMATCH] Your documents appear to belong to different people: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta. Please upload documents for Rajesh Kumar only.

<details><summary>Full trace</summary>

```
Claim CLM-BD87BF64: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [PATIENT_MISMATCH] Your documents appear to belong to different people: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta. Please upload documents for Rajesh Kumar only.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: prescription_rajesh.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F005: extracted via METADATA (confidence 0.50)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: bill_arjun.jpg: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F006: extracted via METADATA (confidence 0.50)
    8. [WARN] DocumentVerificationAgent: Patient mismatch across documents: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta.
```
</details>

## TC004 — Clean Consultation — Full Approval

**Complete, valid consultation claim with correct documents, valid member, covered treatment, within all limits.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹1,350 of ₹1,500, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-6A5450B0: DECIDED.

Decision: APPROVED — approved ₹1,350 of ₹1,500 (confidence 0.98).
  All checks passed. Approved ₹1,350 of ₹1,500.
Financial breakdown:
  COPAY: ₹1,500 -> ₹1,350 (Co-pay (10%) applied: member bears ₹150, insurer pays ₹1,350.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F007: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F007: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F008: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F008: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [PASS] ConsistencyAgent: Patient name 'Rajesh Kumar' consistent across documents.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹1,500).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP001 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹1,500 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-11-01 is on/after the end of the 30-day initial waiting period (2024-05-01).
   20. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   21. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   22. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   23. [PASS] AdjudicationEngine: Per-claim limit: Claimed ₹1,500 is within the per-claim limit of ₹5,000.
   24. [PASS] AdjudicationEngine: COPAY: ₹1,500 -> ₹1,350. Co-pay (10%) applied: member bears ₹150, insurer pays ₹1,350.
   25. [PASS] AdjudicationEngine: Financial summary: eligible ₹1,500 -> approved ₹1,350.
   26. [PASS] FraudAgent: No fraud signals detected.
   27. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   28. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   29. [PASS] DecisionSynthesizer: Decision: APPROVED — approved ₹1,350, confidence 0.98.
```
</details>

## TC005 — Waiting Period — Diabetes

**Member joined 2024-09-01. Claims for diabetes treatment on 2024-10-15, which is within the 90-day waiting period for diabetes.**

- Status: `DECIDED`
- Decision: `REJECTED`, approved ₹0 of ₹3,000, confidence 0.98
- Rejection reasons: ['WAITING_PERIOD']

<details><summary>Full trace</summary>

```
Claim CLM-FC8476F5: DECIDED.

Decision: REJECTED — approved ₹0 of ₹3,000 (confidence 0.98).
  diabetes: 90-day waiting period not served. Eligible from 2024-11-30.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹3,000, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F009: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F009: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F010: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F010: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [PASS] ConsistencyAgent: Patient name 'Vikram Joshi' consistent across documents.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹3,000).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP005 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹3,000 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-15 is on/after the end of the 30-day initial waiting period (2024-10-01).
   20. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   21. [FAIL] AdjudicationEngine: Waiting period — diabetes: diabetes: 90-day waiting period not served. Eligible from 2024-11-30.
   22. [PASS] FraudAgent: No fraud signals detected.
   23. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   24. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   25. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>

## TC006 — Dental Partial Approval — Cosmetic Exclusion

**Bill includes root canal treatment (covered) and teeth whitening (cosmetic, excluded). System must approve only the covered procedure.**

- Status: `DECIDED`
- Decision: `PARTIAL`, approved ₹8,000 of ₹12,000, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-43DC7DE6: DECIDED.

Decision: PARTIAL — approved ₹8,000 of ₹12,000 (confidence 0.98).
  Approved ₹8,000 of ₹12,000.
  Rejected line items:
  - Teeth Whitening (₹4,000): 'Teeth Whitening' is in the policy's excluded dental procedures list.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: DENTAL, ₹12,000, 1 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F011: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F011: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [PASS] DocumentVerificationAgent: Document set satisfies DENTAL requirements (required: ['HOSPITAL_BILL']).
    6. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
    7. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
    8. [PASS] ConsistencyAgent: Patient name 'Priya Singh' consistent across documents.
    9. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   10. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹12,000).
   11. [PASS] AdjudicationEngine: Member validity: Member EMP002 found in policy roster.
   12. [PASS] AdjudicationEngine: Category coverage: DENTAL is a covered category under this policy.
   13. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   14. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹12,000 meets the minimum of ₹500.
   15. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-15 is on/after the end of the 30-day initial waiting period (2024-05-01).
   16. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   17. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   18. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   19. [SKIP] AdjudicationEngine: Per-claim limit: governs CONSULTATION claims; DENTAL is bounded by its category sub-limit (₹10,000).
   20. [PASS] AdjudicationEngine: Line item approved: 'Root Canal Treatment' ₹8,000.
   21. [FAIL] AdjudicationEngine: Line item rejected: 'Teeth Whitening' ₹4,000 — 'Teeth Whitening' is in the policy's excluded dental procedures list.
   22. [PASS] AdjudicationEngine: Financial summary: eligible ₹8,000 -> approved ₹8,000.
   23. [PASS] FraudAgent: No fraud signals detected.
   24. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   25. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   26. [WARN] DecisionSynthesizer: Decision: PARTIAL — approved ₹8,000, confidence 0.98.
```
</details>

## TC007 — MRI Without Pre-Authorization

**MRI scan costing ₹15,000 submitted without pre-authorization. Policy requires pre-auth for MRI above ₹10,000.**

- Status: `DECIDED`
- Decision: `REJECTED`, approved ₹0 of ₹15,000, confidence 0.98
- Rejection reasons: ['PRE_AUTH_MISSING']
- Notes: ['No patient name could be extracted from any document.']

<details><summary>Full trace</summary>

```
Claim CLM-4181F6D8: DECIDED.

Decision: REJECTED — approved ₹0 of ₹15,000 (confidence 0.98).
  'MRI Lumbar Spine' (MRI, ₹15,000) is a high-value test requiring pre-authorization above ₹10,000. No pre-authorization reference was submitted. The member should obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: DIAGNOSTIC, ₹15,000, 3 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F014: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F014: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F013: read as LAB_REPORT (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F013: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    9. [PASS] DocumentPerceptionAgent: F012: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
   10. [PASS] ExtractionAgent: F012: extracted via PROVIDED_CONTENT (confidence 1.00)
   11. [PASS] DocumentVerificationAgent: Document set satisfies DIAGNOSTIC requirements (required: ['PRESCRIPTION', 'LAB_REPORT', 'HOSPITAL_BILL']).
   12. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   13. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   14. [WARN] ConsistencyAgent: No patient name could be extracted from any document.
   15. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   16. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹15,000).
   17. [PASS] ConsistencyAgent: Prescription present.
   18. [PASS] AdjudicationEngine: Member validity: Member EMP007 found in policy roster.
   19. [PASS] AdjudicationEngine: Category coverage: DIAGNOSTIC is a covered category under this policy.
   20. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   21. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹15,000 meets the minimum of ₹500.
   22. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-11-02 is on/after the end of the 30-day initial waiting period (2024-05-01).
   23. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   24. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   25. [FAIL] AdjudicationEngine: Pre-authorization: 'MRI Lumbar Spine' (MRI, ₹15,000) is a high-value test requiring pre-authorization above ₹10,000. No pre-authorization reference was submitted. The member should obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number.
   26. [PASS] FraudAgent: No fraud signals detected.
   27. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   28. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   29. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>

## TC008 — Per-Claim Limit Exceeded

**Claimed amount of ₹7,500 exceeds the per-claim limit of ₹5,000.**

- Status: `DECIDED`
- Decision: `REJECTED`, approved ₹0 of ₹7,500, confidence 0.98
- Rejection reasons: ['PER_CLAIM_EXCEEDED']
- Notes: ['No patient name could be extracted from any document.']

<details><summary>Full trace</summary>

```
Claim CLM-F9028375: DECIDED.

Decision: REJECTED — approved ₹0 of ₹7,500 (confidence 0.98).
  Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹7,500, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F015: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F015: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F016: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F016: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [WARN] ConsistencyAgent: No patient name could be extracted from any document.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹7,500).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP003 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹7,500 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-20 is on/after the end of the 30-day initial waiting period (2024-05-01).
   20. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   21. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   22. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   23. [FAIL] AdjudicationEngine: Per-claim limit: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.
   24. [PASS] FraudAgent: No fraud signals detected.
   25. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   26. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   27. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>

## TC009 — Fraud Signal — Multiple Same-Day Claims

**Member EMP008 has already submitted 3 claims today before this one arrives. This is the 4th claim from the same member on the same day.**

- Status: `DECIDED`
- Decision: `MANUAL_REVIEW`, approved ₹0 of ₹4,800, confidence 0.98
- Fraud signals: ['SAME_DAY_VELOCITY']
- Notes: ['No patient name could be extracted from any document.']

<details><summary>Full trace</summary>

```
Claim CLM-2B84BB47: DECIDED.

Decision: MANUAL_REVIEW — approved ₹0 of ₹4,800 (confidence 0.98).
  Routed to manual review due to fraud/risk signals:
  - This is claim #4 from member EMP008 on 2024-10-30 (policy limit: 2/day). Prior same-day claims: CLM_0081 ₹1,200 at City Clinic A, CLM_0082 ₹1,800 at City Clinic B, CLM_0083 ₹2,100 at Wellness Center
Financial breakdown:
  SUB_LIMIT_CAP: ₹4,800 -> ₹2,000 (CONSULTATION sub-limit of ₹2,000 applied (₹4,800 capped to ₹2,000).)
  COPAY: ₹2,000 -> ₹1,800 (Co-pay (10%) applied: member bears ₹200, insurer pays ₹1,800.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹4,800, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F017: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F017: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F018: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F018: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [WARN] ConsistencyAgent: No patient name could be extracted from any document.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹4,800).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP008 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹4,800 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-30 is on/after the end of the 30-day initial waiting period (2024-05-01).
   20. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   21. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   22. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   23. [PASS] AdjudicationEngine: Per-claim limit: Claimed ₹4,800 is within the per-claim limit of ₹5,000.
   24. [PASS] AdjudicationEngine: SUB_LIMIT_CAP: ₹4,800 -> ₹2,000. CONSULTATION sub-limit of ₹2,000 applied (₹4,800 capped to ₹2,000).
   25. [PASS] AdjudicationEngine: COPAY: ₹2,000 -> ₹1,800. Co-pay (10%) applied: member bears ₹200, insurer pays ₹1,800.
   26. [PASS] AdjudicationEngine: Financial summary: eligible ₹4,800 -> approved ₹1,800.
   27. [WARN] FraudAgent: SAME_DAY_VELOCITY: This is claim #4 from member EMP008 on 2024-10-30 (policy limit: 2/day). Prior same-day claims: CLM_0081 ₹1,200 at City Clinic A, CLM_0082 ₹1,800 at City Clinic B, CLM_0083 ₹2,100 at Wellness Center
   28. [PASS] FraudAgent: Fraud score 0.70; manual review REQUIRED.
   29. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   30. [WARN] DecisionSynthesizer: Decision: MANUAL_REVIEW — approved ₹0, confidence 0.98.
```
</details>

## TC010 — Network Hospital — Discount Applied

**Valid claim at Apollo Hospitals, a network hospital. Network discount must be applied before co-pay.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹3,240 of ₹4,500, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-D5EA0915: DECIDED.

Decision: APPROVED — approved ₹3,240 of ₹4,500 (confidence 0.98).
  All checks passed. Approved ₹3,240 of ₹4,500.
Financial breakdown:
  NETWORK_DISCOUNT: ₹4,500 -> ₹3,600 (Network discount (20%) applied: ₹4,500 -> ₹3,600.)
  COPAY: ₹3,600 -> ₹3,240 (Co-pay (10%) applied: member bears ₹360, insurer pays ₹3,240.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹4,500, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F019: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F019: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F020: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F020: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [PASS] ConsistencyAgent: Patient name 'Deepak Shah' consistent across documents.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹4,500).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP010 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹4,500 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-11-03 is on/after the end of the 30-day initial waiting period (2024-05-01).
   20. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   21. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   22. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   23. [PASS] AdjudicationEngine: Per-claim limit: Claimed ₹4,500 is within the per-claim limit of ₹5,000.
   24. [PASS] AdjudicationEngine: Provider 'Apollo Hospitals' is a network hospital.
   25. [PASS] AdjudicationEngine: NETWORK_DISCOUNT: ₹4,500 -> ₹3,600. Network discount (20%) applied: ₹4,500 -> ₹3,600.
   26. [PASS] AdjudicationEngine: COPAY: ₹3,600 -> ₹3,240. Co-pay (10%) applied: member bears ₹360, insurer pays ₹3,240.
   27. [PASS] AdjudicationEngine: Financial summary: eligible ₹4,500 -> approved ₹3,240.
   28. [PASS] FraudAgent: No fraud signals detected.
   29. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   30. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   31. [PASS] DecisionSynthesizer: Decision: APPROVED — approved ₹3,240, confidence 0.98.
```
</details>

## TC011 — Component Failure — Graceful Degradation

**One component of your system fails mid-processing (simulate with the flag below). The overall pipeline must continue, produce a decision, and make the failure visible in the output with an appropriately reduced confidence score.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹4,000 of ₹4,000, confidence 0.73
- Degraded: YES — failures: ['ConsistencyAgent']
- Notes: ['Processing was incomplete: ConsistencyAgent failed and was skipped. Manual review is recommended before payout.', 'Confidence (0.73) is below 0.80; manual review is recommended.', 'Cross-validation was skipped after a component failure.']

<details><summary>Full trace</summary>

```
Claim CLM-18A7B0D7: DECIDED.

Decision: APPROVED — approved ₹4,000 of ₹4,000 (confidence 0.73).
  All checks passed. Approved ₹4,000 of ₹4,000.
WARNING: processing was degraded (see component failures).

Pipeline trace:
    1. [PASS] Pipeline: Claim received: ALTERNATIVE_MEDICINE, ₹4,000, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F021: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F021: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F022: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F022: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies ALTERNATIVE_MEDICINE requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [FAIL] ConsistencyAgent: Component failed and was skipped: RuntimeError: Simulated component failure (fault injection). Fallback: consistency checks skipped; decision made on extracted data only.
   11. [PASS] AdjudicationEngine: Member validity: Member EMP006 found in policy roster.
   12. [PASS] AdjudicationEngine: Category coverage: ALTERNATIVE_MEDICINE is a covered category under this policy.
   13. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   14. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹4,000 meets the minimum of ₹500.
   15. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-28 is on/after the end of the 30-day initial waiting period (2024-05-01).
   16. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   17. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   18. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   19. [SKIP] AdjudicationEngine: Per-claim limit: governs CONSULTATION claims; ALTERNATIVE_MEDICINE is bounded by its category sub-limit (₹8,000).
   20. [PASS] AdjudicationEngine: Financial summary: eligible ₹4,000 -> approved ₹4,000.
   21. [PASS] FraudAgent: No fraud signals detected.
   22. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   23. [PASS] DecisionSynthesizer: Confidence computed: 0.73 (extraction quality x component-failure penalties).
   24. [PASS] DecisionSynthesizer: Decision: APPROVED — approved ₹4,000, confidence 0.73.
```
</details>

## TC012 — Excluded Treatment

**Member claims for bariatric consultation and a diet program. Obesity treatment is explicitly excluded under the policy.**

- Status: `DECIDED`
- Decision: `REJECTED`, approved ₹0 of ₹8,000, confidence 0.98
- Rejection reasons: ['EXCLUDED_CONDITION']
- Notes: ['No patient name could be extracted from any document.']

<details><summary>Full trace</summary>

```
Claim CLM-A38C114B: DECIDED.

Decision: REJECTED — approved ₹0 of ₹8,000 (confidence 0.98).
  Treatment relates to 'Morbid Obesity — BMI 37', which falls under the policy exclusion 'Obesity and weight loss programs'. Excluded conditions are never payable under this policy.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹8,000, 2 document(s).
    2. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    3. [PASS] DocumentPerceptionAgent: F023: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] ExtractionAgent: F023: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [SKIP] DocumentPerceptionAgent: No LLM — DocumentPerceptionAgent using deterministic read/extract path.
    6. [PASS] DocumentPerceptionAgent: F024: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    7. [PASS] ExtractionAgent: F024: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    9. [SKIP] ClinicalTaggingAgent: No LLM configured — clinical agent skipped; deterministic tags retained.
   10. [SKIP] ConsistencyAgent: No chat model — ConsistencyAgent running check tools directly.
   11. [WARN] ConsistencyAgent: No patient name could be extracted from any document.
   12. [PASS] ConsistencyAgent: Document dates checked against treatment date.
   13. [PASS] ConsistencyAgent: Claimed amount matches bill total (₹8,000).
   14. [PASS] ConsistencyAgent: Prescription present.
   15. [PASS] AdjudicationEngine: Member validity: Member EMP009 found in policy roster.
   16. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   17. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   18. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹8,000 meets the minimum of ₹500.
   19. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-18 is on/after the end of the 30-day initial waiting period (2024-05-01).
   20. [FAIL] AdjudicationEngine: Policy exclusions: Treatment relates to 'Morbid Obesity — BMI 37', which falls under the policy exclusion 'Obesity and weight loss programs'. Excluded conditions are never payable under this policy.
   21. [SKIP] AdjudicationEngine: Claim excluded — remaining hard checks not evaluated (an excluded condition is never payable).
   22. [PASS] FraudAgent: No fraud signals detected.
   23. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   24. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   25. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>
