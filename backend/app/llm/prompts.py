"""Prompts for LLM perception tasks.

Prompts live in one module so they can be reviewed and versioned together.
Each prompt is paired with a strict output schema (see app/agents) — the
model fills a form, it does not converse.

There is exactly ONE vision prompt: a single read of each document produces
classification, extraction and policy-vocabulary tagging in one call
(2N -> N LLM calls per claim). Judgment is never delegated to the model —
it fills fields; deterministic code decides.
"""

DOCUMENT_READ_PROMPT = """You are reading one uploaded medical document for an Indian health insurance claim (category: {category}).

PART 1 — Classify the document into exactly one type:
- PRESCRIPTION: a doctor's Rx — doctor name/registration, diagnosis, medicines (Rx section)
- HOSPITAL_BILL: an itemized hospital/clinic invoice with line items and a total
- PHARMACY_BILL: a pharmacy/chemist bill — medicines with batch/MRP columns, drug license number
- LAB_REPORT: a diagnostic lab report — test names, results, units, normal ranges
- DIAGNOSTIC_REPORT: an imaging/scan report (MRI, CT, X-ray, ultrasound)
- DISCHARGE_SUMMARY: a hospital discharge summary
- DENTAL_REPORT: a dental treatment report
- UNKNOWN: none of the above, or not a medical document at all

Also assess quality: GOOD (clearly readable), LOW (partially readable — blurry regions or stamps over text), UNREADABLE (cannot reliably read the key contents — names, amounts). Be strict about UNREADABLE: never guess an unreadable document's contents.

PART 2 — Extract every field you can read. Rules:
- Copy names EXACTLY as written (patient, doctor). Do not normalize or guess spelling.
- doctor_registration: Indian format like KA/45678/2015 or AYUR/KL/2345/2019 — copy verbatim.
- Dates: return ISO format YYYY-MM-DD. Indian docs often use DD-MM-YYYY or DD-Mon-YYYY.
- line_items: every billed row with its amount as a number (no currency symbols).
- total_amount: the final payable total as a number. If only a subtotal is visible, use it and note it in unreadable_fields.
- diagnosis / treatment / medicines / tests_ordered: copy medical terms verbatim, including shorthand (e.g. "T2DM", "HTN").
- If a field is present but illegible (stamp over text, blur, handwriting you cannot read), leave it null and add the field name to unreadable_fields. NEVER invent values.
- overall_confidence: 1.0 = every key field clearly read; reduce proportionally for illegible or missing fields.
- classification_confidence: how certain the PART 1 classification is.

PART 3 — Map the clinical content onto the policy vocabulary. Copy entries VERBATIM from the lists below; never invent entries; when unsure, leave empty.

matched_conditions — condition keys clearly indicated by the diagnosis/treatment:
{condition_keys}

matched_exclusions — policy exclusions the treatment clearly falls under (entry must be verbatim from this list; evidence = the document text that indicates it):
{exclusion_entries}

line item matched_policy_item — if a billed line clearly corresponds to a {category} procedure/item below, set it verbatim on that line item:
  covered: {covered_procedures}
  excluded: {excluded_procedures}

line item matched_high_value_test — if a billed line is one of these high-value diagnostics, set the canonical name verbatim (e.g. "Magnetic Resonance Imaging" -> MRI, "HRCT Chest" -> CT Scan): {high_value_tests}

line item is_consultation_fee — set true if the line is a doctor consultation/visit fee (any wording: "OPD visit", "doctor charges", "physician fee"), false for tests/medicines/procedures."""

NAME_RECONCILIATION_PROMPT = """You are comparing two Indian names for an insurance claim. Decide whether they plausibly refer to the SAME person.

Name on policy roster: {member_name}
Name on medical document: {doc_name}

Indian name conventions to allow:
- Initials expanded or abbreviated either way ("R. Kumar" ~ "Rajesh Kumar")
- Name-order swaps ("Kumar Rajesh" ~ "Rajesh Kumar")
- Missing middle names or honorifics (Dr./Shri/Smt.)
- Common transliteration variants of the SAME name ("Sneha" ~ "Sneha")

Be conservative: different given names ("Arjun" vs "Rajesh") or clearly different people must return same_person=false. When in doubt, return false."""

MEMBER_MESSAGE_PROMPT = """Rewrite this insurance claim status message for the member in warm, plain language. Rules:
- Keep the outcome and ALL numbers (amounts, dates, percentages) EXACTLY as given — never change, round, or invent figures.
- 2-3 sentences, empathetic and professional, no jargon.
- Do not add advice, promises, or timelines that are not in the original.

Original message: {template_message}"""

CLINICAL_CONSISTENCY_PROMPT = """You are evaluating medical consistency for an Indian health insurance claim.
Diagnosis: {diagnosis}
Treatment / Procedures: {treatment}
Medicines Prescribed: {medicines}
Tests Ordered: {tests}

Decide if the treatment, medicines, and tests are clinically consistent and standard for the stated diagnosis.
- Return consistent=true if they align with standard medical practice.
- Return consistent=false ONLY if there is an obvious clinical mismatch or anomaly. Provide a 1-sentence rationale."""

OPS_SUMMARY_PROMPT = """You are an AI assistant writing a 3-bullet executive briefing for an operations manager reviewing a health insurance claim decision.
Claim ID: {claim_id}
Status: {status}
Decision: {decision_value} (Approved ₹{approved_amount:,.0f} of ₹{claimed_amount:,.0f})
Reasons: {reasons}
Warnings / Signals: {warnings}

Generate 3 concise, professional bullet points highlighting:
1. Member eligibility & claim type overview
2. Adjudication & financial outcome
3. Any risk signals, warnings, or required ops actions"""

