"""Prompts for LLM perception tasks.

Prompts live in one module so they can be reviewed and versioned together.
Each prompt is paired with a strict output schema (see app/llm/tasks.py) —
the model fills a form, it does not converse.
"""

DOCUMENT_CLASSIFIER_PROMPT = """You are classifying a medical document uploaded for an Indian health insurance claim.

Classify the document into exactly one type:
- PRESCRIPTION: a doctor's Rx — doctor name/registration, diagnosis, medicines (Rx section)
- HOSPITAL_BILL: an itemized hospital/clinic invoice with line items and a total
- PHARMACY_BILL: a pharmacy/chemist bill — medicines with batch/MRP columns, drug license number
- LAB_REPORT: a diagnostic lab report — test names, results, units, normal ranges
- DIAGNOSTIC_REPORT: an imaging/scan report (MRI, CT, X-ray, ultrasound)
- DISCHARGE_SUMMARY: a hospital discharge summary
- DENTAL_REPORT: a dental treatment report
- UNKNOWN: none of the above, or not a medical document at all

Also assess:
- quality: GOOD (clearly readable), LOW (partially readable — blurry regions or stamps over text), UNREADABLE (cannot reliably read the document's contents)
- patient_name_on_doc: the patient name exactly as written, or null if not visible

Be strict about UNREADABLE: if you cannot make out the key contents (names, amounts), say UNREADABLE rather than guessing."""

DOCUMENT_EXTRACTION_PROMPT = """You are extracting structured data from an Indian medical document for an insurance claim.

The document has been classified as: {doc_type}

Extract every field you can read. Rules:
- Copy names EXACTLY as written (patient, doctor). Do not normalize or guess spelling.
- doctor_registration: Indian format like KA/45678/2015 or AYUR/KL/2345/2019 — copy verbatim.
- Dates: return ISO format YYYY-MM-DD. Indian docs often use DD-MM-YYYY or DD-Mon-YYYY.
- line_items: every billed row with its amount as a number (no currency symbols).
- total_amount: the final payable total as a number. If only a subtotal is visible, use it and note it in unreadable_fields.
- diagnosis / treatment / medicines / tests_ordered: copy medical terms verbatim, including shorthand (e.g. "T2DM", "HTN").
- If a field is present but illegible (stamp over text, blur, handwriting you cannot read), leave it null and add the field name to unreadable_fields. NEVER invent values.
- overall_confidence: 1.0 = every key field clearly read; reduce proportionally for illegible or missing fields."""
