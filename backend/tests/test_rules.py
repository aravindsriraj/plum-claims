"""Unit tests for the deterministic rules layer.

These pin the exact behaviors the assignment's test cases demand. They use
the REAL policy file (data/policy_terms.json) — no mocks — so a policy edit
that breaks behavior fails here loudly.
"""

from datetime import date

import pytest

from app.contracts.documents import ExtractedDocument, LineItem
from app.contracts.enums import ClaimCategory, DocumentType, ExtractionMethod
from app.contracts.inputs import ClaimInput, DocumentInput, PriorClaim
from app.observability.trace import TraceRecorder
from app.policy.loader import load_policy
from app.rules.adjudication import adjudicate
from app.rules.financial import (
    apply_copay,
    apply_network_discount,
    is_network_hospital,
)
from app.rules.fraud import assess_fraud
from app.rules.tagging import tag_deterministic
from app.rules.waiting import (
    check_initial_waiting_period,
    check_specific_waiting_periods,
)

POLICY = load_policy()


def make_claim(**overrides) -> ClaimInput:
    base = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500,
        documents=[DocumentInput(file_id="F1")],
    )
    base.update(overrides)
    return ClaimInput(**base)


def make_doc(
    file_id="F1",
    doc_type=DocumentType.HOSPITAL_BILL,
    line_items=None,
    total=None,
    diagnosis=None,
    provider=None,
) -> ExtractedDocument:
    return ExtractedDocument(
        file_id=file_id,
        doc_type=doc_type,
        method=ExtractionMethod.PROVIDED_CONTENT,
        line_items=line_items or [],
        total_amount=total,
        diagnosis=diagnosis,
        provider_name=provider,
        patient_name="Test Patient",
    )


def run(claim, docs):
    return adjudicate(claim, POLICY, docs, TraceRecorder())


# ---------------------------------------------------------------- conditions
class TestConditionMatching:
    def test_diabetes_matches(self):
        assert "diabetes" in tag_deterministic(POLICY, "Type 2 Diabetes Mellitus").conditions

    def test_joint_pain_is_not_joint_replacement(self):
        # TC011: "Chronic Joint Pain" must NOT trigger the 730-day joint
        # replacement waiting period.
        assert "joint_replacement" not in tag_deterministic(POLICY, "Chronic Joint Pain").conditions

    def test_obesity_matches(self):
        matched = tag_deterministic(POLICY, "Morbid Obesity — BMI 37").conditions
        assert "obesity_treatment" in matched


# ---------------------------------------------------------------- exclusions
class TestExclusions:
    def test_bariatric_consultation_excluded(self):
        tags = tag_deterministic(
            POLICY,
            "Morbid Obesity — BMI 37",
            "Bariatric Consultation and Customised Diet Plan",
        )
        entries = {t.entry for t in tags.exclusions}
        assert "Obesity and weight loss programs" in entries or "Bariatric surgery" in entries

    def test_viral_fever_not_excluded(self):
        assert not tag_deterministic(POLICY, "Viral Fever").exclusions


# ------------------------------------------------------------------ tagging
class TestTagMerging:
    """Hybrid semantics: union, provenance on every tag, disagreements flagged."""

    def test_llm_recall_merged_with_deterministic_floor(self):
        from app.contracts.documents import DocumentTags, PolicyTag
        from app.rules.tagging import merge_tags

        det = tag_deterministic(POLICY, "Type 2 Diabetes Mellitus")
        llm = DocumentTags(
            conditions=["diabetes", "hypertension"],  # hypertension = LLM-only recall
            exclusions=[],
        )
        merged = merge_tags(llm, det, file_id="F1")
        assert set(merged.tags.conditions) == {"diabetes", "hypertension"}
        # The LLM-only condition is surfaced as an alias-gap warning.
        assert any("hypertension" in w for w in merged.warnings)

    def test_exclusion_found_by_both_marked_both(self):
        from app.contracts.documents import DocumentTags, PolicyTag
        from app.rules.tagging import merge_tags

        det = tag_deterministic(POLICY, "Morbid Obesity — BMI 37")
        entry = det.exclusions[0].entry
        llm = DocumentTags(exclusions=[PolicyTag(entry=entry, matched_text="BMI 37", via="llm")])
        merged = merge_tags(llm, det)
        merged_tag = next(t for t in merged.tags.exclusions if t.entry == entry)
        assert merged_tag.via == "both"
        assert not merged.warnings  # agreement is not a disagreement

    def test_no_llm_tags_returns_deterministic_verbatim(self):
        from app.rules.tagging import merge_tags

        det = tag_deterministic(POLICY, "Type 2 Diabetes Mellitus")
        merged = merge_tags(None, det)
        assert merged.tags is det
        assert not merged.warnings


class TestLlmTagValidation:
    """LLM tags are whitelist-checked against the policy vocabulary."""

    def test_hallucinated_condition_dropped_and_flagged(self):
        from app.contracts.documents import DocumentTags
        from app.rules.tagging import validate_llm_tags

        raw = DocumentTags(conditions=["diabetes", "alien_fever"], exclusions=[])
        clean, warnings = validate_llm_tags(raw, POLICY)
        assert clean.conditions == ["diabetes"]
        assert any("alien_fever" in w for w in warnings)

    def test_hallucinated_exclusion_dropped_and_flagged(self):
        from app.contracts.documents import DocumentTags, PolicyTag
        from app.rules.tagging import validate_llm_tags

        raw = DocumentTags(exclusions=[
            PolicyTag(entry="Substance abuse treatment", matched_text="rehab", via="llm"),
            PolicyTag(entry="Invented exclusion", matched_text="x", via="llm"),
        ])
        clean, warnings = validate_llm_tags(raw, POLICY)
        assert [t.entry for t in clean.exclusions] == ["Substance abuse treatment"]
        assert any("Invented exclusion" in w for w in warnings)

    def test_aliases_come_from_policy_file_not_code(self):
        """The policy JSON is the vocabulary's single source of truth."""
        from app.policy.loader import Policy

        custom = Policy(raw={
            **POLICY.raw,
            "matching_aliases": {"conditions": {"diabetes": ["sugar problem"]}, "exclusions": {}},
        })
        tags = tag_deterministic(custom, "Patient has a sugar problem")
        assert tags.conditions == ["diabetes"]
        # And the stock alias no longer fires under the custom vocabulary.
        assert not tag_deterministic(custom, "Type 2 Diabetes Mellitus").conditions


# ------------------------------------------------------------------ waiting
class TestWaitingPeriods:
    def test_initial_waiting_period_math(self):
        # Joined 2024-09-01, treated 2024-10-15 -> 44 days, past 30-day initial.
        r = check_initial_waiting_period(date(2024, 9, 1), date(2024, 10, 15), 30)
        assert r.passed

    def test_diabetes_waiting_period_blocks_with_eligible_date(self):
        # TC005: joined 2024-09-01, diabetes treatment 2024-10-15 (day 44 < 90).
        [r] = check_specific_waiting_periods(
            date(2024, 9, 1), date(2024, 10, 15), ["diabetes"], {"diabetes": 90}
        )
        assert not r.passed
        assert r.eligible_from == date(2024, 11, 30)  # join + 90 days
        assert "2024-11-30" in r.reason


# ----------------------------------------------------------------- financial
class TestFinancialEngine:
    def test_network_discount_before_copay(self):
        # TC010 pins the ordering: 4500 -> 3600 (20% off) -> 3240 (10% copay).
        rules = POLICY.category_rules(ClaimCategory.CONSULTATION)
        discounted, adj = apply_network_discount(4500, True, rules)
        assert discounted == 3600
        payable, _ = apply_copay(discounted, rules)
        assert payable == 3240

    def test_non_network_gets_no_discount(self):
        assert not is_network_hospital("City Clinic, Bengaluru", POLICY.network_hospitals)
        assert is_network_hospital("Apollo Hospitals", POLICY.network_hospitals)

    def test_network_matching_is_fuzzy(self):
        assert is_network_hospital("Apollo Hospitals, Bengaluru", POLICY.network_hospitals)
        assert is_network_hospital("Fortis Healthcare", POLICY.network_hospitals)


# ------------------------------------------------------------------- fraud
class TestFraud:
    def test_same_day_velocity_triggers_manual_review(self):
        # TC009: 3 prior same-day claims, this is the 4th; limit is 2/day.
        history = [
            PriorClaim(claim_id=f"CLM_008{i}", date=date(2024, 10, 30), amount=a, provider=p)
            for i, (a, p) in enumerate(
                [(1200, "City Clinic A"), (1800, "City Clinic B"), (2100, "Wellness Center")],
                start=1,
            )
        ]
        assessment = assess_fraud(
            "EMP008", date(2024, 10, 30), 4800, history, POLICY.fraud_thresholds
        )
        assert assessment.requires_manual_review
        codes = {s.code for s in assessment.signals}
        assert "SAME_DAY_VELOCITY" in codes

    def test_clean_history_no_manual_review(self):
        assessment = assess_fraud(
            "EMP001", date(2024, 11, 1), 1500, [], POLICY.fraud_thresholds
        )
        assert not assessment.requires_manual_review
        assert assessment.fraud_score == 0


# ------------------------------------------------------------- adjudication
class TestAdjudication:
    def test_tc004_clean_consultation_full_approval_math(self):
        claim = make_claim(ytd_claims_amount=5000)
        docs = [
            make_doc(
                file_id="F008",
                line_items=[
                    LineItem(description="Consultation Fee", amount=1000),
                    LineItem(description="CBC Test", amount=300),
                    LineItem(description="Dengue NS1 Test", amount=200),
                ],
                total=1500,
                provider="City Clinic, Bengaluru",
            )
        ]
        result = run(claim, docs)
        assert not result.hard_failed
        # Consultation portion 1000 < 2000 sub-limit; no network; 10% co-pay on 1500.
        assert result.approved_amount == 1350

    def test_tc005_diabetes_waiting_period_rejects_with_date(self):
        claim = make_claim(
            member_id="EMP005",
            treatment_date=date(2024, 10, 15),
            claimed_amount=3000,
        )
        docs = [make_doc(diagnosis="Type 2 Diabetes Mellitus", total=3000)]
        result = run(claim, docs)
        assert result.hard_failed
        assert "WAITING_PERIOD" in result.rejection_reasons
        failing = next(c for c in result.checks if not c.passed)
        assert "2024-11-30" in failing.reason

    def test_tc006_dental_partial_cosmetic_excluded(self):
        claim = make_claim(
            member_id="EMP002",
            claim_category=ClaimCategory.DENTAL,
            treatment_date=date(2024, 10, 15),
            claimed_amount=12000,
        )
        docs = [
            make_doc(
                line_items=[
                    LineItem(description="Root Canal Treatment", amount=8000),
                    LineItem(description="Teeth Whitening", amount=4000),
                ],
                total=12000,
                provider="Smile Dental Clinic",
            )
        ]
        result = run(claim, docs)
        assert not result.hard_failed
        by_desc = {li.description: li for li in result.line_items}
        assert by_desc["Root Canal Treatment"].status == "APPROVED"
        assert by_desc["Teeth Whitening"].status == "REJECTED"
        assert by_desc["Teeth Whitening"].rejection_reason
        assert result.approved_amount == 8000

    def test_tc007_mri_without_pre_auth_rejected(self):
        claim = make_claim(
            member_id="EMP007",
            claim_category=ClaimCategory.DIAGNOSTIC,
            treatment_date=date(2024, 11, 2),
            claimed_amount=15000,
        )
        docs = [
            make_doc(
                file_id="F013",
                doc_type=DocumentType.LAB_REPORT,
                diagnosis="Suspected Lumbar Disc Herniation",
            ),
            make_doc(
                file_id="F014",
                line_items=[LineItem(description="MRI Lumbar Spine", amount=15000)],
                total=15000,
            ),
        ]
        result = run(claim, docs)
        assert result.hard_failed
        assert "PRE_AUTH_MISSING" in result.rejection_reasons
        failing = next(c for c in result.checks if not c.passed)
        assert "pre-authorization" in failing.reason.lower()
        assert "resubmit" in failing.reason.lower()

    def test_tc008_per_claim_limit_rejected(self):
        claim = make_claim(
            member_id="EMP003",
            treatment_date=date(2024, 10, 20),
            claimed_amount=7500,
            ytd_claims_amount=10000,
        )
        docs = [
            make_doc(
                line_items=[
                    LineItem(description="Consultation Fee", amount=2000),
                    LineItem(description="Medicines", amount=5500),
                ],
                total=7500,
                diagnosis="Gastroenteritis",
            )
        ]
        result = run(claim, docs)
        assert result.hard_failed
        assert "PER_CLAIM_EXCEEDED" in result.rejection_reasons
        failing = next(c for c in result.checks if not c.passed)
        assert "7,500" in failing.reason and "5,000" in failing.reason

    def test_tc010_network_discount_full_pipeline(self):
        claim = make_claim(
            member_id="EMP010",
            treatment_date=date(2024, 11, 3),
            claimed_amount=4500,
            hospital_name="Apollo Hospitals",
            ytd_claims_amount=8000,
        )
        docs = [
            make_doc(
                line_items=[
                    LineItem(description="Consultation Fee", amount=1500),
                    LineItem(description="Medicines", amount=3000),
                ],
                total=4500,
                provider="Apollo Hospitals",
                diagnosis="Acute Bronchitis",
            )
        ]
        result = run(claim, docs)
        assert not result.hard_failed
        assert result.approved_amount == 3240
        kinds = [a.kind for a in result.adjustments]
        # Discount strictly before co-pay.
        assert kinds.index("NETWORK_DISCOUNT") < kinds.index("COPAY")

    def test_tc012_excluded_condition_rejected(self):
        claim = make_claim(
            member_id="EMP009",
            treatment_date=date(2024, 10, 18),
            claimed_amount=8000,
        )
        docs = [
            make_doc(
                diagnosis="Morbid Obesity — BMI 37",
                line_items=[
                    LineItem(description="Bariatric Consultation", amount=3000),
                    LineItem(description="Personalised Diet and Nutrition Program", amount=5000),
                ],
                total=8000,
            )
        ]
        result = run(claim, docs)
        assert result.hard_failed
        assert "EXCLUDED_CONDITION" in result.rejection_reasons

    def test_unknown_member_rejected(self):
        claim = make_claim(member_id="EMP999")
        result = run(claim, [make_doc(total=1500)])
        assert result.hard_failed
        assert "MEMBER_NOT_FOUND" in result.rejection_reasons

    def test_tags_drive_adjudication_without_clinical_text(self):
        """A document tagged upstream (no raw diagnosis) still triggers the
        diabetes waiting period — the engine consumes tags, not text."""
        from app.contracts.documents import DocumentTags

        claim = make_claim(
            member_id="EMP005",
            treatment_date=date(2024, 10, 15),
            claimed_amount=3000,
        )
        doc = make_doc(total=3000)  # no diagnosis text at all
        doc.tags = DocumentTags(conditions=["diabetes"], exclusions=[])
        result = run(claim, [doc])
        assert result.hard_failed
        assert "WAITING_PERIOD" in result.rejection_reasons
