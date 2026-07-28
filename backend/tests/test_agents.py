"""Tests for the agent layer: verification, extraction, cross-validation,
decision synthesis, confidence, and the resilience wrapper.

No LLM calls here — agents are tested through their deterministic paths
(simulation metadata / provided content), which is exactly how the eval
harness exercises them.
"""

from datetime import date

import pytest

from app.agents.cross_validation import cross_validate
from app.agents.decision import synthesize
from app.agents.document_verification import verify_documents
from app.agents.extraction import extract_documents
from app.contracts.decision import AdjudicationResult, FraudAssessment, FraudSignal
from app.contracts.enums import (
    ClaimCategory,
    Decision,
    DocumentIssueCode,
    DocumentQuality,
    DocumentType,
)
from app.contracts.inputs import ClaimInput, DocumentInput
from app.contracts.trace import ComponentFailure
from app.observability.confidence import compute_confidence
from app.observability.resilience import run_resilient
from app.observability.trace import TraceRecorder
from app.policy.loader import load_policy

POLICY = load_policy()


def doc(file_id, **kwargs) -> DocumentInput:
    return DocumentInput(file_id=file_id, **kwargs)


# ------------------------------------------------------- document verification
class TestDocumentVerification:
    def test_tc001_two_prescriptions_specific_messages(self):
        classified, issues, _ = verify_documents(
            ClaimCategory.CONSULTATION,
            "Rajesh Kumar",
            [
                doc("F001", file_name="dr_sharma_prescription.jpg", actual_type=DocumentType.PRESCRIPTION),
                doc("F002", file_name="another_prescription.jpg", actual_type=DocumentType.PRESCRIPTION),
            ],
            POLICY,
            TraceRecorder(),
        )
        codes = {i.code for i in issues}
        assert DocumentIssueCode.MISSING_DOCUMENT in codes
        assert DocumentIssueCode.WRONG_DOCUMENT_TYPE in codes
        joined = " ".join(i.message for i in issues)
        # Message must name the uploaded type AND the required type.
        assert "prescription" in joined.lower()
        assert "hospital bill" in joined.lower()
        assert "another_prescription.jpg" in joined

    def test_tc002_unreadable_asks_reupload_not_rejection(self):
        _, issues, _ = verify_documents(
            ClaimCategory.PHARMACY,
            "Sneha Reddy",
            [
                doc("F003", actual_type=DocumentType.PRESCRIPTION, quality=DocumentQuality.GOOD),
                doc("F004", file_name="blurry_bill.jpg", actual_type=DocumentType.PHARMACY_BILL,
                    quality=DocumentQuality.UNREADABLE),
            ],
            POLICY,
            TraceRecorder(),
        )
        unreadable = [i for i in issues if i.code == DocumentIssueCode.UNREADABLE_DOCUMENT]
        assert len(unreadable) == 1
        assert "re-upload" in unreadable[0].message.lower()
        assert "not been rejected" in unreadable[0].message.lower()
        assert "blurry_bill.jpg" in unreadable[0].message
        # Unreadable doc must NOT also be flagged as wrong type (noise).
        assert not any(
            i.code == DocumentIssueCode.WRONG_DOCUMENT_TYPE and i.file_id == "F004"
            for i in issues
        )

    def test_tc003_patient_mismatch_names_both_patients(self):
        _, issues, _ = verify_documents(
            ClaimCategory.CONSULTATION,
            "Rajesh Kumar",
            [
                doc("F005", actual_type=DocumentType.PRESCRIPTION, patient_name_on_doc="Rajesh Kumar"),
                doc("F006", actual_type=DocumentType.HOSPITAL_BILL, patient_name_on_doc="Arjun Mehta"),
            ],
            POLICY,
            TraceRecorder(),
        )
        mismatches = [i for i in issues if i.code == DocumentIssueCode.PATIENT_MISMATCH]
        assert len(mismatches) == 1
        assert "Rajesh Kumar" in mismatches[0].message
        assert "Arjun Mehta" in mismatches[0].message

    def test_clean_document_set_no_issues(self):
        _, issues, _ = verify_documents(
            ClaimCategory.DIAGNOSTIC,
            "Suresh Patil",
            [
                doc("F1", actual_type=DocumentType.PRESCRIPTION, patient_name_on_doc="Suresh Patil"),
                doc("F2", actual_type=DocumentType.LAB_REPORT, patient_name_on_doc="Suresh Patil"),
                doc("F3", actual_type=DocumentType.HOSPITAL_BILL, patient_name_on_doc="Suresh Patil"),
            ],
            POLICY,
            TraceRecorder(),
        )
        assert issues == []


# ---------------------------------------------------------------- extraction
class TestExtraction:
    def test_provided_content_maps_all_fields(self):
        documents = [
            doc(
                "F1",
                actual_type=DocumentType.HOSPITAL_BILL,
                content={
                    "patient_name": "Rajesh Kumar",
                    "hospital_name": "City Clinic, Bengaluru",
                    "date": "2024-11-01",
                    "line_items": [{"description": "Consultation Fee", "amount": 1000}],
                    "total": 1000,
                },
            )
        ]
        from app.agents.document_verification import read_document

        classified = [read_document(documents[0], None, POLICY, ClaimCategory.CONSULTATION)[0]]
        [extracted] = extract_documents(documents, classified, TraceRecorder(), POLICY)
        assert extracted.patient_name == "Rajesh Kumar"
        assert extracted.provider_name == "City Clinic, Bengaluru"
        assert extracted.document_date == date(2024, 11, 1)
        assert extracted.total_amount == 1000
        assert extracted.line_items[0].description == "Consultation Fee"
        assert extracted.overall_confidence == 1.0

    def test_metadata_only_document_gets_shell(self):
        documents = [doc("F1", actual_type=DocumentType.PRESCRIPTION, patient_name_on_doc="X")]
        from app.agents.document_verification import read_document

        classified = [read_document(documents[0], None, POLICY, ClaimCategory.CONSULTATION)[0]]
        [extracted] = extract_documents(documents, classified, TraceRecorder(), POLICY)
        assert extracted.patient_name == "X"
        assert extracted.overall_confidence == 0.5

    def test_vision_read_shapes_document_and_merges_tags(self):
        """The single read flows through: fields land, LLM tags are validated
        and union-merged with the deterministic matcher."""
        import base64

        from app.agents.document_verification import LlmDocumentRead, LlmExclusionTag
        from app.contracts.documents import ClassifiedDocument
        from app.contracts.enums import ExtractionMethod

        documents = [
            doc(
                "F1",
                actual_type=None,
                file_content_base64=base64.b64encode(b"fake-image").decode(),
                mime_type="image/jpeg",
            )
        ]
        # The classified shell as verification would have produced it.
        classified = [
            ClassifiedDocument(
                file_id="F1",
                detected_type=DocumentType.PRESCRIPTION,
                detection_confidence=0.95,
                quality=DocumentQuality.GOOD,
                patient_name_on_doc="Rajesh Kumar",
                method=ExtractionMethod.VISION_LLM,
            )
        ]
        read = LlmDocumentRead(
            doc_type=DocumentType.PRESCRIPTION,
            quality=DocumentQuality.GOOD,
            classification_confidence=0.95,
            patient_name="Rajesh Kumar",
            diagnosis="Type 2 Diabetes Mellitus with high sugar",
            overall_confidence=0.9,
            matched_conditions=["diabetes", "alien_fever"],  # one hallucinated
            matched_exclusions=[LlmExclusionTag(entry="Invented exclusion", evidence="x")],
        )
        trace = TraceRecorder()
        [extracted] = extract_documents(
            documents, classified, trace, POLICY, llm_reads={"F1": read}
        )
        assert extracted.patient_name == "Rajesh Kumar"
        assert extracted.diagnosis.startswith("Type 2")
        # Hallucinated tags dropped; real tags merged (LLM + deterministic agree).
        assert extracted.tags.conditions == ["diabetes"]
        assert extracted.tags.exclusions == []
        warnings = [e.summary for e in trace.events if e.status == "WARN"]
        assert any("alien_fever" in w for w in warnings)
        assert any("Invented exclusion" in w for w in warnings)


# ------------------------------------------------------------ cross-validation
class TestCrossValidation:
    def make_claim(self, amount=1500):
        return ClaimInput(
            member_id="EMP001",
            policy_id="PLUM_GHI_2024",
            claim_category=ClaimCategory.CONSULTATION,
            treatment_date=date(2024, 11, 1),
            claimed_amount=amount,
            documents=[doc("F1")],
        )

    def test_amount_mismatch_warns(self):
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="Rajesh Kumar",
                total_amount=9999,
            )
        ]
        warnings = cross_validate(self.make_claim(), "Rajesh Kumar", docs, POLICY, TraceRecorder())
        assert any("differs" in w for w in warnings)

    def test_consistent_docs_no_amount_warning(self):
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="Rajesh Kumar",
                total_amount=1500,
                document_date=date(2024, 11, 1),
            )
        ]
        warnings = cross_validate(self.make_claim(), "Rajesh Kumar", docs, POLICY, TraceRecorder())
        assert not any("differs" in w for w in warnings)

    def test_provider_mismatch_form_vs_document_warns(self):
        """Form says Apollo, bill says City Medical Centre -> must flag."""
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        claim = self.make_claim()
        claim.hospital_name = "Apollo Hospitals"
        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="Rajesh Kumar",
                provider_name="City Medical Centre",
                total_amount=1500,
            )
        ]
        warnings = cross_validate(claim, "Rajesh Kumar", docs, POLICY, TraceRecorder())
        assert any("Provider mismatch" in w for w in warnings)

    def test_llm_name_reconciliation_clears_mismatch_warning(self):
        """When names mismatch ('R. Kumar' vs 'Rajesh Kumar'), an LLM second opinion
        can confirm they refer to the same person and suppress the warning."""
        from app.agents.cross_validation import LlmNameVerdict
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        class FakeLlm:
            call_count = 1

            def structured(self, schema, prompt, **kwargs):
                return LlmNameVerdict(same_person=True, rationale="Initial abbreviation")

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="R. Kumar",
                total_amount=1500,
            )
        ]
        trace = TraceRecorder()
        warnings = cross_validate(
            self.make_claim(), "Rajesh Kumar", docs, POLICY, trace, llm=FakeLlm()
        )
        assert not any("patient name" in w for w in warnings)
        assert any("reconciled with member" in e.summary for e in trace.events)

    def test_llm_name_reconciliation_keeps_warning_when_different_person(self):
        """If the LLM concludes they are different people, the warning remains."""
        from app.agents.cross_validation import LlmNameVerdict
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        class FakeLlm:
            call_count = 1

            def structured(self, schema, prompt, **kwargs):
                return LlmNameVerdict(same_person=False, rationale="Different people")

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="Arjun Mehta",
                total_amount=1500,
            )
        ]
        warnings = cross_validate(
            self.make_claim(), "Rajesh Kumar", docs, POLICY, TraceRecorder(), llm=FakeLlm()
        )
        assert any("do not match" in w for w in warnings)

    def test_llm_clinical_consistency_checks_treatment_aligns_with_diagnosis(self):
        """Clinical consistency check uses LLM to flag medical anomalies."""
        from app.agents.cross_validation import LlmClinicalVerdict, LlmNameVerdict
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        class FakeLlm:
            call_count = 1

            def structured(self, schema, prompt, **kwargs):
                if schema == LlmNameVerdict:
                    return LlmNameVerdict(same_person=True)
                return LlmClinicalVerdict(
                    consistent=False, rationale="Dental scaling is unusual for hypertension"
                )

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                patient_name="Rajesh Kumar",
                diagnosis="Essential Hypertension",
                treatment="Dental Scaling",
                total_amount=1500,
            )
        ]
        trace = TraceRecorder()
        warnings = cross_validate(
            self.make_claim(), "Rajesh Kumar", docs, POLICY, trace, llm=FakeLlm()
        )
        assert any("Clinical inconsistency" in w for w in warnings)


# ------------------------------------------------------------------- member message
class TestMemberMessagePolisher:
    def test_preserved_figures_returns_polished_text(self):
        from app.agents.member_message import LlmMemberMessage, polish_member_message

        class FakeLlm:
            def structured(self, schema, prompt, **kwargs):
                return LlmMemberMessage(
                    message="Great news! Your claim was approved. We will pay ₹1,350 out of ₹1,500."
                )

        template = "Your claim has been approved. ₹1,350 of ₹1,500 will be paid."
        trace = TraceRecorder()
        result = polish_member_message(template, FakeLlm(), trace)
        assert "Great news!" in result
        assert "₹1,350" in result and "₹1,500" in result

    def test_dropped_figure_falls_back_to_template(self):
        from app.agents.member_message import LlmMemberMessage, polish_member_message

        class FakeLlm:
            def structured(self, schema, prompt, **kwargs):
                # Dropped the ₹1,350 figure!
                return LlmMemberMessage(message="Your claim was approved for full payment.")

        template = "Your claim has been approved. ₹1,350 of ₹1,500 will be paid."
        trace = TraceRecorder()
        result = polish_member_message(template, FakeLlm(), trace)
        # Should fall back to template because ₹1,350 was missing
        assert result == template
        assert any("dropped or altered a figure" in e.summary for e in trace.events)


# ------------------------------------------------------------------- decision
class TestDecisionSynthesis:
    def test_fraud_overrides_clean_adjudication(self):
        decision = synthesize(
            claimed_amount=4800,
            adjudication=AdjudicationResult(approved_amount=4320),
            fraud=FraudAssessment(
                fraud_score=0.7,
                signals=[FraudSignal(code="SAME_DAY_VELOCITY", description="4th claim today", severity=0.7)],
                requires_manual_review=True,
            ),
            confidence=0.95,
            failures=[],
            cross_validation_warnings=[],
            trace=TraceRecorder(),
        )
        assert decision.decision == Decision.MANUAL_REVIEW
        assert decision.approved_amount == 0
        assert any("4th claim" in r for r in decision.reasons)

    def test_degraded_approval_gets_manual_review_note(self):
        decision = synthesize(
            claimed_amount=4000,
            adjudication=AdjudicationResult(approved_amount=4000),
            fraud=FraudAssessment(),
            confidence=0.73,
            failures=[
                ComponentFailure(
                    component="CrossValidationAgent",
                    error="RuntimeError: simulated",
                    fallback_used="skipped",
                    confidence_penalty=0.25,
                )
            ],
            cross_validation_warnings=[],
            trace=TraceRecorder(),
        )
        assert decision.decision == Decision.APPROVED
        assert decision.degraded
        assert any("Manual review is recommended" in n for n in decision.notes)


# ----------------------------------------------------------------- confidence
class TestConfidence:
    def test_failure_penalty_applied(self):
        from app.contracts.documents import ExtractedDocument
        from app.contracts.enums import ExtractionMethod

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.HOSPITAL_BILL,
                method=ExtractionMethod.PROVIDED_CONTENT,
                total_amount=100,
                overall_confidence=1.0,
            )
        ]
        clean = compute_confidence(docs, [])
        degraded = compute_confidence(
            docs,
            [
                ComponentFailure(
                    component="X", error="e", fallback_used="f", confidence_penalty=0.25
                )
            ],
        )
        assert clean > degraded
        assert clean == 0.98
        assert degraded == round(0.98 * 0.75, 2)


# ----------------------------------------------------------------- resilience
class TestResilience:
    def test_failure_recorded_and_fallback_returned(self):
        trace = TraceRecorder()

        def boom():
            raise TimeoutError("LLM timed out")

        result = run_resilient("SomeAgent", boom, lambda: ["fallback"], trace)
        assert result == ["fallback"]
        assert len(trace.failures) == 1
        assert trace.failures[0].component == "SomeAgent"
        assert "TimeoutError" in trace.failures[0].error
        assert any("SomeAgent" in e.summary or e.component == "SomeAgent" for e in trace.events)

    def test_success_path_untouched(self):
        trace = TraceRecorder()
        result = run_resilient("SomeAgent", lambda: [1, 2, 3], lambda: [], trace)
        assert result == [1, 2, 3]
        assert len(trace.failures) == 0


class TestClinicalTaggingAgent:
    def test_skipped_without_llm(self):
        from app.agents.clinical_agent import run_clinical_tagging_agent
        from app.contracts.documents import DocumentTags, ExtractedDocument
        from app.contracts.enums import DocumentType, ExtractionMethod
        from app.observability.trace import TraceRecorder
        from app.policy.loader import load_policy

        docs = [
            ExtractedDocument(
                file_id="F1",
                doc_type=DocumentType.PRESCRIPTION,
                method=ExtractionMethod.PROVIDED_CONTENT,
                diagnosis="Type 2 Diabetes Mellitus",
                tags=DocumentTags(conditions=["diabetes"]),
            )
        ]
        trace = TraceRecorder()
        out = run_clinical_tagging_agent(docs, load_policy(), trace, llm=None)
        assert out[0].tags.conditions == ["diabetes"]
        assert any("clinical agent skipped" in e.summary.lower() for e in trace.events)

    def test_tools_bind_to_policy(self):
        from app.agents.clinical_agent import build_clinical_tools
        from app.policy.loader import load_policy

        tools = build_clinical_tools(load_policy())
        names = {t.name for t in tools}
        assert "lookup_policy_exclusion" in names
        assert "check_condition_waiting_period" in names
        assert "verify_high_value_test" in names
