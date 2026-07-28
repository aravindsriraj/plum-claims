"""Policy loader: the single source of truth for all coverage rules.

Every rule the AdjudicationEngine applies comes from `policy_terms.json`
through this module. Nothing about coverage, limits, waiting periods,
exclusions or matching vocabulary is hardcoded anywhere else in the
codebase — swap the JSON file and the system's behavior changes accordingly.

Matching aliases ship pre-normalized (see app/rules/textnorm.normalize) so
the per-claim matchers never re-normalize static policy text.
"""

from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.contracts.enums import ClaimCategory, DocumentType
from app.rules.textnorm import normalize

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class OpdCategoryRules(BaseModel):
    """Rules for one OPD category, mirroring `opd_categories` in the policy file."""

    sub_limit: float
    copay_percent: float = 0
    network_discount_percent: float = 0
    requires_prescription: bool = False
    requires_pre_auth: bool = False
    pre_auth_threshold: float | None = None
    high_value_tests_requiring_pre_auth: list[str] = Field(default_factory=list)
    requires_dental_report: bool = False
    requires_registered_practitioner: bool = False
    max_sessions_per_year: int | None = None
    covered_procedures: list[str] = Field(default_factory=list)
    excluded_procedures: list[str] = Field(default_factory=list)
    covered_items: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)
    covered_systems: list[str] = Field(default_factory=list)
    branded_drug_copay_percent: float | None = None
    generic_mandatory: bool = False
    covered: bool = True


class DocumentRequirement(BaseModel):
    required: list[DocumentType]
    optional: list[DocumentType] = Field(default_factory=list)


class Member(BaseModel):
    member_id: str
    name: str
    date_of_birth: str
    gender: str
    relationship: str
    join_date: str | None = None  # dependents don't carry one; resolved via primary
    primary_member_id: str | None = None
    dependents: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    """Typed view over the raw policy JSON, with convenience accessors."""

    raw: dict

    @property
    def policy_id(self) -> str:
        return self.raw["policy_id"]

    @property
    def sum_insured(self) -> float:
        return float(self.raw["coverage"]["sum_insured_per_employee"])

    @property
    def annual_opd_limit(self) -> float:
        return float(self.raw["coverage"]["annual_opd_limit"])

    @property
    def per_claim_limit(self) -> float:
        return float(self.raw["coverage"]["per_claim_limit"])

    @property
    def policy_start_date(self) -> str:
        return self.raw["policy_holder"]["policy_start_date"]

    def category_rules(self, category: ClaimCategory) -> OpdCategoryRules:
        """Rules for a claim category, e.g. CONSULTATION -> opd_categories.consultation."""
        key = category.value.lower()
        try:
            return OpdCategoryRules(**self.raw["opd_categories"][key])
        except KeyError as exc:
            raise ValueError(f"Policy has no OPD rules for category {category.value}") from exc

    def document_requirement(self, category: ClaimCategory) -> DocumentRequirement:
        """Required/optional document types for a claim category."""
        return DocumentRequirement(**self.raw["document_requirements"][category.value])

    @property
    def initial_waiting_period_days(self) -> int:
        return int(self.raw["waiting_periods"]["initial_waiting_period_days"])

    @property
    def pre_existing_waiting_days(self) -> int:
        return int(self.raw["waiting_periods"]["pre_existing_conditions_days"])

    @property
    def specific_condition_waiting_days(self) -> dict[str, int]:
        """Condition keyword -> waiting days, e.g. {"diabetes": 90, ...}."""
        return {k: int(v) for k, v in self.raw["waiting_periods"]["specific_conditions"].items()}

    @property
    def excluded_conditions(self) -> list[str]:
        return list(self.raw["exclusions"]["conditions"])

    @cached_property
    def condition_aliases(self) -> dict[str, list[str]]:
        """Condition key -> normalized alias phrases (normalized once, cached)."""
        return {
            key: [normalize(a) for a in aliases]
            for key, aliases in self.raw.get("matching_aliases", {}).get("conditions", {}).items()
        }

    @cached_property
    def exclusion_aliases(self) -> dict[str, list[str]]:
        """Verbatim policy exclusion entry -> normalized alias phrases."""
        return {
            entry: [normalize(a) for a in aliases]
            for entry, aliases in self.raw.get("matching_aliases", {}).get("exclusions", {}).items()
        }

    @cached_property
    def network_hospitals_normalized(self) -> list[str]:
        """Network hospital names, pre-normalized for containment matching."""
        return [normalize(h) for h in self.network_hospitals]

    @property
    def network_hospitals(self) -> list[str]:
        return list(self.raw["network_hospitals"])

    @property
    def submission_deadline_days(self) -> int:
        return int(self.raw["submission_rules"]["deadline_days_from_treatment"])

    @property
    def minimum_claim_amount(self) -> float:
        return float(self.raw["submission_rules"]["minimum_claim_amount"])

    @property
    def fraud_thresholds(self) -> dict:
        return dict(self.raw["fraud_thresholds"])

    def find_member(self, member_id: str) -> Member | None:
        """Look up a member (employee or dependent) in the roster."""
        for m in self.raw["members"]:
            if m["member_id"] == member_id:
                return Member(**m)
        return None

    def member_join_date(self, member: Member) -> str | None:
        """A member's coverage start. Dependents inherit their primary's join date."""
        if member.join_date:
            return member.join_date
        if member.primary_member_id:
            primary = self.find_member(member.primary_member_id)
            return primary.join_date if primary else None
        return None


@lru_cache(maxsize=1)
def load_policy(path: Path | None = None) -> Policy:
    """Load and cache the policy file. Cached so every component shares one instance."""
    import json

    policy_path = path or DATA_DIR / "policy_terms.json"
    with open(policy_path, encoding="utf-8") as f:
        return Policy(raw=json.load(f))
