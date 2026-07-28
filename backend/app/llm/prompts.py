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
  excluded: {excluded_procedures}"""
