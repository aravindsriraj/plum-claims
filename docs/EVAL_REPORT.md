# Eval Report — 12 Test Cases

Generated: 2026-07-28T20:47:44  
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
Claim CLM-2B6F50D7: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [MISSING_DOCUMENT] Your consultation claim requires a hospital bill, but you uploaded 'dr_sharma_prescription.jpg' (PRESCRIPTION), 'another_prescription.jpg' (PRESCRIPTION). Please upload your hospital bill to continue.
  [WRONG_DOCUMENT_TYPE] 'another_prescription.jpg' is a prescription, but we still need your hospital bill. Please upload the correct document.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [PASS] DocumentVerificationAgent: dr_sharma_prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: another_prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    4. [WARN] DocumentVerificationAgent: Required document HOSPITAL_BILL is missing from the upload.
    5. [WARN] DocumentVerificationAgent: F002: PRESCRIPTION does not satisfy the requirements.
```
</details>

## TC002 — Unreadable Document

**Member uploads a valid prescription but a blurry, unreadable photo of their pharmacy bill.**

- Status: `DOCUMENT_REJECTED`
- Member-facing issues:
  - [UNREADABLE_DOCUMENT] We couldn't read your pharmacy bill ('blurry_bill.jpg') — the image is too blurry or damaged. Please re-upload a clear photo of that same document. Your claim has NOT been rejected; it will continue once we can read this document.

<details><summary>Full trace</summary>

```
Claim CLM-21CFC42E: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [UNREADABLE_DOCUMENT] We couldn't read your pharmacy bill ('blurry_bill.jpg') — the image is too blurry or damaged. Please re-upload a clear photo of that same document. Your claim has NOT been rejected; it will continue once we can read this document.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: PHARMACY, ₹800, 2 document(s).
    2. [PASS] DocumentVerificationAgent: prescription.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: blurry_bill.jpg: read as PHARMACY_BILL (quality UNREADABLE, confidence 1.00, via METADATA).
    4. [WARN] DocumentVerificationAgent: F004: document unreadable, re-upload requested.
```
</details>

## TC003 — Documents Belong to Different Patients

**The prescription is for Rajesh Kumar but the hospital bill is for a different patient, Arjun Mehta.**

- Status: `DOCUMENT_REJECTED`
- Member-facing issues:
  - [PATIENT_MISMATCH] Your documents appear to belong to different people: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta. Please upload documents for Rajesh Kumar only.

<details><summary>Full trace</summary>

```
Claim CLM-F37AD1B1: DOCUMENT_REJECTED.

Processing stopped at document verification:
  [PATIENT_MISMATCH] Your documents appear to belong to different people: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta. Please upload documents for Rajesh Kumar only.

No claim decision was made.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [PASS] DocumentVerificationAgent: prescription_rajesh.jpg: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: bill_arjun.jpg: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [WARN] DocumentVerificationAgent: Patient mismatch across documents: 'prescription_rajesh.jpg' belongs to Rajesh Kumar; 'bill_arjun.jpg' belongs to Arjun Mehta.
```
</details>

## TC004 — Clean Consultation — Full Approval

**Complete, valid consultation claim with correct documents, valid member, covered treatment, within all limits.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹1,350 of ₹1,500, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-803AFC17: DECIDED.

Decision: APPROVED — approved ₹1,350 of ₹1,500 (confidence 0.98).
  All checks passed. Approved ₹1,350 of ₹1,500.
Financial breakdown:
  COPAY: ₹1,500 -> ₹1,350 (Co-pay (10%) applied: member bears ₹150, insurer pays ₹1,350.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹1,500, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F007: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F008: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F007: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F008: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [PASS] CrossValidationAgent: Patient name 'Rajesh Kumar' consistent across documents.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹1,500).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Consultation Fee' (₹1,000) does not require pre-authorization.
   12. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'CBC Test' (₹300) does not require pre-authorization.
   13. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Dengue NS1 Test' (₹200) does not require pre-authorization.
   14. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 0 waiting period(s), 3 pre-auth alert(s).
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
Claim CLM-058F7A4B: DECIDED.

Decision: REJECTED — approved ₹0 of ₹3,000 (confidence 0.98).
  diabetes: 90-day waiting period not served. Eligible from 2024-11-30.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹3,000, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F009: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F010: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F009: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F010: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [PASS] CrossValidationAgent: Patient name 'Vikram Joshi' consistent across documents.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹3,000).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [PASS] ClinicalReasoningAgent: Tool finding: WAITING_PERIOD: 'diabetes' carries a mandatory 90-day waiting period.
   12. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 1 waiting period(s), 0 pre-auth alert(s).
   13. [PASS] AdjudicationEngine: Member validity: Member EMP005 found in policy roster.
   14. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   15. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   16. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹3,000 meets the minimum of ₹500.
   17. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-15 is on/after the end of the 30-day initial waiting period (2024-10-01).
   18. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   19. [FAIL] AdjudicationEngine: Waiting period — diabetes: diabetes: 90-day waiting period not served. Eligible from 2024-11-30.
   20. [PASS] FraudAgent: No fraud signals detected.
   21. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   22. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   23. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>

## TC006 — Dental Partial Approval — Cosmetic Exclusion

**Bill includes root canal treatment (covered) and teeth whitening (cosmetic, excluded). System must approve only the covered procedure.**

- Status: `DECIDED`
- Decision: `PARTIAL`, approved ₹8,000 of ₹12,000, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-B58A63E9: DECIDED.

Decision: PARTIAL — approved ₹8,000 of ₹12,000 (confidence 0.98).
  Approved ₹8,000 of ₹12,000.
  Rejected line items:
  - Teeth Whitening (₹4,000): 'Teeth Whitening' is in the policy's excluded dental procedures list.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: DENTAL, ₹12,000, 1 document(s).
    2. [PASS] DocumentVerificationAgent: F011: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: Document set satisfies DENTAL requirements (required: ['HOSPITAL_BILL']).
    4. [PASS] ExtractionAgent: F011: extracted via PROVIDED_CONTENT (confidence 1.00)
    5. [PASS] CrossValidationAgent: Patient name 'Priya Singh' consistent across documents.
    6. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    7. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹12,000).
    8. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Root Canal Treatment' (₹8,000) does not require pre-authorization.
    9. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Teeth Whitening' (₹4,000) does not require pre-authorization.
   10. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 0 waiting period(s), 2 pre-auth alert(s).
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
Claim CLM-EB6F91EA: DECIDED.

Decision: REJECTED — approved ₹0 of ₹15,000 (confidence 0.98).
  'MRI Lumbar Spine' (MRI, ₹15,000) is a high-value test requiring pre-authorization above ₹10,000. No pre-authorization reference was submitted. The member should obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: DIAGNOSTIC, ₹15,000, 3 document(s).
    2. [PASS] DocumentVerificationAgent: F012: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F013: read as LAB_REPORT (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: F014: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    5. [PASS] DocumentVerificationAgent: Document set satisfies DIAGNOSTIC requirements (required: ['PRESCRIPTION', 'LAB_REPORT', 'HOSPITAL_BILL']).
    6. [PASS] ExtractionAgent: F012: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [PASS] ExtractionAgent: F013: extracted via PROVIDED_CONTENT (confidence 1.00)
    8. [PASS] ExtractionAgent: F014: extracted via PROVIDED_CONTENT (confidence 1.00)
    9. [WARN] CrossValidationAgent: No patient name could be extracted from any document.
   10. [PASS] CrossValidationAgent: Document dates checked against treatment date.
   11. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹15,000).
   12. [PASS] CrossValidationAgent: Prescription present.
   13. [PASS] ClinicalReasoningAgent: Tool finding: WAITING_PERIOD: 'hernia' carries a mandatory 365-day waiting period.
   14. [WARN] ClinicalReasoningAgent: Tool finding: PRE_AUTH_REQUIRED: 'MRI Lumbar Spine' (MRI, ₹15,000) is a high-value test exceeding the ₹10,000 pre-authorization threshold.
   15. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 1 waiting period(s), 1 pre-auth alert(s).
   16. [PASS] AdjudicationEngine: Member validity: Member EMP007 found in policy roster.
   17. [PASS] AdjudicationEngine: Category coverage: DIAGNOSTIC is a covered category under this policy.
   18. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   19. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹15,000 meets the minimum of ₹500.
   20. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-11-02 is on/after the end of the 30-day initial waiting period (2024-05-01).
   21. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   22. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   23. [FAIL] AdjudicationEngine: Pre-authorization: 'MRI Lumbar Spine' (MRI, ₹15,000) is a high-value test requiring pre-authorization above ₹10,000. No pre-authorization reference was submitted. The member should obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number.
   24. [PASS] FraudAgent: No fraud signals detected.
   25. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   26. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   27. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
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
Claim CLM-015E2C70: DECIDED.

Decision: REJECTED — approved ₹0 of ₹7,500 (confidence 0.98).
  Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹7,500, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F015: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F016: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F015: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F016: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [WARN] CrossValidationAgent: No patient name could be extracted from any document.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹7,500).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Consultation Fee' (₹2,000) does not require pre-authorization.
   12. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Medicines' (₹5,500) does not require pre-authorization.
   13. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 0 waiting period(s), 2 pre-auth alert(s).
   14. [PASS] AdjudicationEngine: Member validity: Member EMP003 found in policy roster.
   15. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   16. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   17. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹7,500 meets the minimum of ₹500.
   18. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-20 is on/after the end of the 30-day initial waiting period (2024-05-01).
   19. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   20. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   21. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   22. [FAIL] AdjudicationEngine: Per-claim limit: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.
   23. [PASS] FraudAgent: No fraud signals detected.
   24. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   25. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   26. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
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
Claim CLM-42202429: DECIDED.

Decision: MANUAL_REVIEW — approved ₹0 of ₹4,800 (confidence 0.98).
  Routed to manual review due to fraud/risk signals:
  - This is claim #4 from member EMP008 on 2024-10-30 (policy limit: 2/day). Prior same-day claims: CLM_0081 ₹1,200 at City Clinic A, CLM_0082 ₹1,800 at City Clinic B, CLM_0083 ₹2,100 at Wellness Center
Financial breakdown:
  SUB_LIMIT_CAP: ₹4,800 -> ₹2,000 (CONSULTATION sub-limit of ₹2,000 applied (₹4,800 capped to ₹2,000).)
  COPAY: ₹2,000 -> ₹1,800 (Co-pay (10%) applied: member bears ₹200, insurer pays ₹1,800.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹4,800, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F017: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F018: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F017: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F018: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [WARN] CrossValidationAgent: No patient name could be extracted from any document.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹4,800).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [PASS] ClinicalReasoningAgent: Clinical ReAct Agent verified: all policy tool checks passed.
   12. [PASS] AdjudicationEngine: Member validity: Member EMP008 found in policy roster.
   13. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   14. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   15. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹4,800 meets the minimum of ₹500.
   16. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-30 is on/after the end of the 30-day initial waiting period (2024-05-01).
   17. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   18. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   19. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   20. [PASS] AdjudicationEngine: Per-claim limit: Claimed ₹4,800 is within the per-claim limit of ₹5,000.
   21. [PASS] AdjudicationEngine: SUB_LIMIT_CAP: ₹4,800 -> ₹2,000. CONSULTATION sub-limit of ₹2,000 applied (₹4,800 capped to ₹2,000).
   22. [PASS] AdjudicationEngine: COPAY: ₹2,000 -> ₹1,800. Co-pay (10%) applied: member bears ₹200, insurer pays ₹1,800.
   23. [PASS] AdjudicationEngine: Financial summary: eligible ₹4,800 -> approved ₹1,800.
   24. [WARN] FraudAgent: SAME_DAY_VELOCITY: This is claim #4 from member EMP008 on 2024-10-30 (policy limit: 2/day). Prior same-day claims: CLM_0081 ₹1,200 at City Clinic A, CLM_0082 ₹1,800 at City Clinic B, CLM_0083 ₹2,100 at Wellness Center
   25. [PASS] FraudAgent: Fraud score 0.70; manual review REQUIRED.
   26. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   27. [WARN] DecisionSynthesizer: Decision: MANUAL_REVIEW — approved ₹0, confidence 0.98.
```
</details>

## TC010 — Network Hospital — Discount Applied

**Valid claim at Apollo Hospitals, a network hospital. Network discount must be applied before co-pay.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹3,240 of ₹4,500, confidence 0.98

<details><summary>Full trace</summary>

```
Claim CLM-7C783BEC: DECIDED.

Decision: APPROVED — approved ₹3,240 of ₹4,500 (confidence 0.98).
  All checks passed. Approved ₹3,240 of ₹4,500.
Financial breakdown:
  NETWORK_DISCOUNT: ₹4,500 -> ₹3,600 (Network discount (20%) applied: ₹4,500 -> ₹3,600.)
  COPAY: ₹3,600 -> ₹3,240 (Co-pay (10%) applied: member bears ₹360, insurer pays ₹3,240.)

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹4,500, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F019: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F020: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F019: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F020: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [PASS] CrossValidationAgent: Patient name 'Deepak Shah' consistent across documents.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹4,500).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Consultation Fee' (₹1,500) does not require pre-authorization.
   12. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Medicines' (₹3,000) does not require pre-authorization.
   13. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 0 waiting period(s), 2 pre-auth alert(s).
   14. [PASS] AdjudicationEngine: Member validity: Member EMP010 found in policy roster.
   15. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   16. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   17. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹4,500 meets the minimum of ₹500.
   18. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-11-03 is on/after the end of the 30-day initial waiting period (2024-05-01).
   19. [PASS] AdjudicationEngine: Policy exclusions: No policy exclusion matches the diagnosis/treatment.
   20. [SKIP] AdjudicationEngine: Specific waiting periods: no waiting-listed condition detected (conditions checked: none matched).
   21. [PASS] AdjudicationEngine: Pre-authorization: No pre-authorization required for this claim.
   22. [PASS] AdjudicationEngine: Per-claim limit: Claimed ₹4,500 is within the per-claim limit of ₹5,000.
   23. [PASS] AdjudicationEngine: Provider 'Apollo Hospitals' is a network hospital.
   24. [PASS] AdjudicationEngine: NETWORK_DISCOUNT: ₹4,500 -> ₹3,600. Network discount (20%) applied: ₹4,500 -> ₹3,600.
   25. [PASS] AdjudicationEngine: COPAY: ₹3,600 -> ₹3,240. Co-pay (10%) applied: member bears ₹360, insurer pays ₹3,240.
   26. [PASS] AdjudicationEngine: Financial summary: eligible ₹4,500 -> approved ₹3,240.
   27. [PASS] FraudAgent: No fraud signals detected.
   28. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   29. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   30. [PASS] DecisionSynthesizer: Decision: APPROVED — approved ₹3,240, confidence 0.98.
```
</details>

## TC011 — Component Failure — Graceful Degradation

**One component of your system fails mid-processing (simulate with the flag below). The overall pipeline must continue, produce a decision, and make the failure visible in the output with an appropriately reduced confidence score.**

- Status: `DECIDED`
- Decision: `APPROVED`, approved ₹4,000 of ₹4,000, confidence 0.73
- Degraded: YES — failures: ['CrossValidationAgent']
- Notes: ['Processing was incomplete: CrossValidationAgent failed and was skipped. Manual review is recommended before payout.', 'Confidence (0.73) is below 0.80; manual review is recommended.', 'Cross-validation was skipped after a component failure.']

<details><summary>Full trace</summary>

```
Claim CLM-E1AE9AC8: DECIDED.

Decision: APPROVED — approved ₹4,000 of ₹4,000 (confidence 0.73).
  All checks passed. Approved ₹4,000 of ₹4,000.
WARNING: processing was degraded (see component failures).

Pipeline trace:
    1. [PASS] Pipeline: Claim received: ALTERNATIVE_MEDICINE, ₹4,000, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F021: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F022: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies ALTERNATIVE_MEDICINE requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F021: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F022: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [FAIL] CrossValidationAgent: Component failed and was skipped: RuntimeError: Simulated component failure (fault injection). Fallback: consistency checks skipped; decision made on extracted data only.
    8. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Panchakarma Therapy (5 sessions)' (₹3,000) does not require pre-authorization.
    9. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Consultation' (₹1,000) does not require pre-authorization.
   10. [PASS] ClinicalReasoningAgent: Clinical findings: 0 exclusion(s), 0 waiting period(s), 2 pre-auth alert(s).
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
Claim CLM-CBFEE32B: DECIDED.

Decision: REJECTED — approved ₹0 of ₹8,000 (confidence 0.98).
  Treatment relates to 'Morbid Obesity — BMI 37', which falls under the policy exclusion 'Obesity and weight loss programs'. Excluded conditions are never payable under this policy.

Pipeline trace:
    1. [PASS] Pipeline: Claim received: CONSULTATION, ₹8,000, 2 document(s).
    2. [PASS] DocumentVerificationAgent: F023: read as PRESCRIPTION (quality GOOD, confidence 1.00, via METADATA).
    3. [PASS] DocumentVerificationAgent: F024: read as HOSPITAL_BILL (quality GOOD, confidence 1.00, via METADATA).
    4. [PASS] DocumentVerificationAgent: Document set satisfies CONSULTATION requirements (required: ['PRESCRIPTION', 'HOSPITAL_BILL']).
    5. [PASS] ExtractionAgent: F023: extracted via PROVIDED_CONTENT (confidence 1.00)
    6. [PASS] ExtractionAgent: F024: extracted via PROVIDED_CONTENT (confidence 1.00)
    7. [WARN] CrossValidationAgent: No patient name could be extracted from any document.
    8. [PASS] CrossValidationAgent: Document dates checked against treatment date.
    9. [PASS] CrossValidationAgent: Claimed amount matches bill total (₹8,000).
   10. [PASS] CrossValidationAgent: Prescription present.
   11. [WARN] ClinicalReasoningAgent: Tool finding: EXCLUDED: 'Morbid Obesity — BMI 37' matches policy exclusion 'Obesity and weight loss programs'. Evidence: 'Morbid Obesity — BMI 37'. Excluded conditions are non-payable.
   12. [WARN] ClinicalReasoningAgent: Tool finding: EXCLUDED: 'Bariatric Consultation and Customised Diet Plan' matches policy exclusion 'Obesity and weight loss programs'. Evidence: 'Bariatric Consultation and Customised Diet Plan'. Excluded conditions are non-payable.
   13. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Bariatric Consultation' (₹3,000) does not require pre-authorization.
   14. [WARN] ClinicalReasoningAgent: Tool finding: NO_PRE_AUTH_REQUIRED: 'Personalised Diet and Nutrition Program' (₹5,000) does not require pre-authorization.
   15. [PASS] ClinicalReasoningAgent: Clinical findings: 2 exclusion(s), 0 waiting period(s), 2 pre-auth alert(s).
   16. [PASS] AdjudicationEngine: Member validity: Member EMP009 found in policy roster.
   17. [PASS] AdjudicationEngine: Category coverage: CONSULTATION is a covered category under this policy.
   18. [SKIP] AdjudicationEngine: Submission deadline: NOT_EVALUATED (no submission_date provided).
   19. [PASS] AdjudicationEngine: Minimum claim amount: Claimed ₹8,000 meets the minimum of ₹500.
   20. [PASS] AdjudicationEngine: Initial waiting period: Treatment date 2024-10-18 is on/after the end of the 30-day initial waiting period (2024-05-01).
   21. [FAIL] AdjudicationEngine: Policy exclusions: Treatment relates to 'Morbid Obesity — BMI 37', which falls under the policy exclusion 'Obesity and weight loss programs'. Excluded conditions are never payable under this policy.
   22. [SKIP] AdjudicationEngine: Claim excluded — remaining hard checks not evaluated (an excluded condition is never payable).
   23. [PASS] FraudAgent: No fraud signals detected.
   24. [PASS] FraudAgent: Fraud score 0.00; manual review not required.
   25. [PASS] DecisionSynthesizer: Confidence computed: 0.98 (extraction quality x component-failure penalties).
   26. [FAIL] DecisionSynthesizer: Decision: REJECTED — approved ₹0, confidence 0.98.
```
</details>
