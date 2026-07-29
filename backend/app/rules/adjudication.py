"""AdjudicationEngine: deterministic policy evaluation.

Every rule here reads parameters from the loaded Policy object (policy_terms.json).
No coverage logic is hardcoded; only the evaluation sequence lives in code.

Rule order:
  1. Member validity          — must be on policy roster
  2. Submission deadline      — only when submission_date is provided
  3. Minimum claim amount     — sanity check
  4. Initial waiting period   — blanket gate before clinical checks
  5. Exclusions               — excluded condition short-circuits all checks
  6. Specific waiting periods — condition-level waiting gates
  7. Pre-authorization        — high-value tests or category pre-auth
  8. Per-claim limit          — cap for consultation claims
  9. Line-item adjudication   — covered vs excluded procedures
 10. Financial computation    — sub-limit -> network discount -> co-pay
"""

from app.contracts.decision import AdjudicationResult, RuleCheck
from app.contracts.documents import DocumentTags, ExtractedDocument, LineItem, PolicyTag
from app.contracts.enums import ClaimCategory, LineItemStatus
from app.contracts.inputs import ClaimInput
from app.observability.trace import TraceRecorder
from app.policy.loader import Policy
from app.rules.financial import (
    apply_copay,
    apply_network_discount,
    apply_sub_limit,
    is_network_hospital,
)
from app.rules.tagging import is_consultation_fee, match_high_value_test, tag_deterministic
from app.rules.textnorm import contains_normalized, normalize
from app.rules.waiting import check_initial_waiting_period, check_specific_waiting_periods
from app.util import parse_iso_date

COMPONENT = "AdjudicationEngine"


def _clinical_texts(docs: list[ExtractedDocument]) -> list[str]:
    texts: list[str] = []
    for d in docs:
        texts.extend(t for t in (d.diagnosis, d.treatment) if t)
        texts.extend(d.tests_ordered)
    return texts


def _all_line_items(docs: list[ExtractedDocument]) -> list[LineItem]:
    return [li.model_copy() for d in docs for li in d.line_items]


def _tags_for(docs: list[ExtractedDocument], policy: Policy) -> DocumentTags:
    conditions: list[str] = []
    exclusions: list[PolicyTag] = []
    seen: set[str] = set()
    for d in docs:
        tags = d.tags or tag_deterministic(policy, d.diagnosis, d.treatment, *d.tests_ordered)
        for c in tags.conditions:
            if c not in conditions:
                conditions.append(c)
        for tag in tags.exclusions:
            if tag.entry not in seen:
                seen.add(tag.entry)
                exclusions.append(tag)
    return DocumentTags(conditions=conditions, exclusions=exclusions)


def _provider_name(claim: ClaimInput, docs: list[ExtractedDocument]) -> str | None:
    for d in docs:
        if d.provider_name:
            return d.provider_name
    return claim.hospital_name


def adjudicate(
    claim: ClaimInput,
    policy: Policy,
    docs: list[ExtractedDocument],
    trace: TraceRecorder,
    llm: LlmClient | None = None,
) -> AdjudicationResult:
    """Run all policy rules for a claim. Every outcome is recorded in the trace."""
    result = AdjudicationResult()
    rules = policy.category_rules(claim.claim_category)
    clinical = _clinical_texts(docs)
    line_items = _all_line_items(docs)
    tags = _tags_for(docs, policy)

    def check(rule_id: str, name: str, passed: bool, reason: str, **detail) -> bool:
        chk = RuleCheck(rule_id=rule_id, name=name, passed=passed, hard_fail=True, reason=reason, detail=detail)
        result.checks.append(chk)
        trace.check(COMPONENT, passed, f"{name}: {reason}", detail)
        if not passed:
            result.rejection_reasons.append(rule_id)
        return passed

    # 1. Member validity
    member = policy.find_member(claim.member_id)
    if not check(
        "MEMBER_NOT_FOUND", "Member validity", member is not None,
        f"Member {claim.member_id} found in policy roster." if member else f"Member {claim.member_id} is not on the policy roster.",
        member_id=claim.member_id,
    ):
        return result
    join_date = parse_iso_date(policy.member_join_date(member))

    # 1b. Category coverage gate
    if not check(
        "CATEGORY_NOT_COVERED", "Category coverage", rules.covered,
        f"{claim.claim_category.value} is a covered category under this policy." if rules.covered else f"{claim.claim_category.value} is not covered under this policy.",
        category=claim.claim_category.value, covered=rules.covered,
    ):
        return result

    # 2. Submission deadline
    if claim.submission_date:
        deadline_days = policy.submission_deadline_days
        days_late = (claim.submission_date - claim.treatment_date).days
        if not check(
            "SUBMISSION_DEADLINE_MISSED", "Submission deadline", days_late <= deadline_days,
            f"Submitted {days_late} days after treatment (limit {deadline_days}).",
            days_after_treatment=days_late, limit=deadline_days,
        ):
            return result
    else:
        trace.skipped(COMPONENT, "Submission deadline: NOT_EVALUATED (no submission_date provided).")

    # 3. Minimum claim amount
    minimum = policy.minimum_claim_amount
    if not check(
        "BELOW_MINIMUM_AMOUNT", "Minimum claim amount", claim.claimed_amount >= minimum,
        f"Claimed ₹{claim.claimed_amount:,.0f} meets the minimum of ₹{minimum:,.0f}."
        if claim.claimed_amount >= minimum
        else f"Claimed ₹{claim.claimed_amount:,.0f} is below the minimum claim amount of ₹{minimum:,.0f}.",
        claimed=claim.claimed_amount, minimum=minimum,
    ):
        return result

    # 4. Initial waiting period
    if join_date:
        initial = check_initial_waiting_period(join_date, claim.treatment_date, policy.initial_waiting_period_days)
        if not check(
            "WAITING_PERIOD", "Initial waiting period", initial.passed, initial.reason,
            join_date=join_date.isoformat(), eligible_from=initial.eligible_from.isoformat(),
        ):
            return result
    else:
        trace.skipped(COMPONENT, "Initial waiting period: NOT_EVALUATED (member join date unavailable).")

    # 5. Exclusions (short-circuits everything)
    if tags.exclusions:
        matched = tags.exclusions[0]
        check(
            "EXCLUDED_CONDITION", "Policy exclusions", False,
            f"Treatment relates to '{matched.matched_text}', which falls under the policy exclusion '{matched.entry}'. Excluded conditions are never payable under this policy.",
            policy_entry=matched.entry, matched_text=matched.matched_text, via=matched.via,
            all_matches=[m.entry for m in tags.exclusions],
        )
        trace.skipped(COMPONENT, "Claim excluded — remaining hard checks not evaluated (an excluded condition is never payable).")
        return result
    check("EXCLUDED_CONDITION", "Policy exclusions", True, "No policy exclusion matches the diagnosis/treatment.", clinical_texts_reviewed=clinical)

    # 6. Specific waiting periods
    if join_date and tags.conditions:
        waiting_results = check_specific_waiting_periods(join_date, claim.treatment_date, tags.conditions, policy.specific_condition_waiting_days)
        for wr in waiting_results:
            if not check(
                "WAITING_PERIOD", f"Waiting period — {wr.condition}", wr.passed, wr.reason,
                condition=wr.condition, waiting_days=wr.days_waiting, eligible_from=wr.eligible_from.isoformat(),
            ):
                return result
    else:
        trace.skipped(COMPONENT, f"Specific waiting periods: no waiting-listed condition detected (conditions checked: {tags.conditions or 'none matched'}).")

    # 7. Pre-authorization
    pre_auth_needed, pre_auth_why = _pre_auth_requirement(claim, rules, line_items, clinical, policy)
    if pre_auth_needed:
        if not check(
            "PRE_AUTH_MISSING", "Pre-authorization", claim.pre_auth_reference is not None,
            f"Pre-authorization obtained (ref {claim.pre_auth_reference})." if claim.pre_auth_reference else f"{pre_auth_why} No pre-authorization reference was submitted. The member should obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number.",
            requirement=pre_auth_why,
        ):
            return result
    else:
        check("PRE_AUTH_MISSING", "Pre-authorization", True, "No pre-authorization required for this claim.")

    # 8. Per-claim limit
    per_claim_limit = policy.per_claim_limit
    applies = claim.claim_category == ClaimCategory.CONSULTATION
    if not applies:
        trace.skipped(COMPONENT, f"Per-claim limit: governs CONSULTATION claims; {claim.claim_category.value} is bounded by its category sub-limit (₹{rules.sub_limit:,.0f}).")
    if applies and not check(
        "PER_CLAIM_EXCEEDED", "Per-claim limit", claim.claimed_amount <= per_claim_limit,
        f"Claimed ₹{claim.claimed_amount:,.0f} is within the per-claim limit of ₹{per_claim_limit:,.0f}."
        if claim.claimed_amount <= per_claim_limit
        else f"Claimed amount ₹{claim.claimed_amount:,.0f} exceeds the per-claim limit of ₹{per_claim_limit:,.0f}.",
        claimed=claim.claimed_amount, per_claim_limit=per_claim_limit,
    ):
        return result

    # 9. Line-item adjudication
    line_items = _adjudicate_line_items(claim.claim_category, rules, line_items, trace)
    result.line_items = line_items
    if not line_items:
        eligible = claim.claimed_amount
    else:
        eligible = sum(
            li.amount for li in line_items if li.status == LineItemStatus.APPROVED
        )
    result.eligible_amount = round(eligible, 2)

    if line_items and eligible == 0:
        check("NO_ELIGIBLE_LINE_ITEMS", "Eligible line items", False, "Every billed line item is excluded under the policy.")
        return result

    # 10. Financial computation
    provider = _provider_name(claim, docs)
    sub_limit_base = _sub_limit_base(claim.claim_category, line_items, eligible, policy)
    remainder = eligible - sub_limit_base
    capped_base, sub_adj = apply_sub_limit(sub_limit_base, claim.claim_category.value, rules)
    eligible_after_cap = round(capped_base + remainder, 2)
    if sub_adj:
        result.adjustments.append(sub_adj)

    network = is_network_hospital(provider, policy.network_hospitals, llm=llm)
    if network:
        trace.info(COMPONENT, f"Provider '{provider}' is a network hospital.")
    discounted, disc_adj = apply_network_discount(eligible_after_cap, network, rules)
    if disc_adj:
        result.adjustments.append(disc_adj)
    payable, copay_adj = apply_copay(discounted, rules)
    if copay_adj:
        result.adjustments.append(copay_adj)
    result.approved_amount = round(payable, 2)

    for adj in result.adjustments:
        trace.info(COMPONENT, f"{adj.kind.value}: ₹{adj.amount_before:,.0f} -> ₹{adj.amount_after:,.0f}. {adj.note}", adj.model_dump())
    trace.info(COMPONENT, f"Financial summary: eligible ₹{result.eligible_amount:,.0f} -> approved ₹{result.approved_amount:,.0f}.")
    return result


def _line_high_value_test(li: LineItem, policy: Policy, known_tests: list[str]) -> str | None:
    if li.matched_high_value_test:
        return li.matched_high_value_test if li.matched_high_value_test in known_tests else None
    return match_high_value_test(policy, li.description)


def _pre_auth_requirement(
    claim: ClaimInput, rules, line_items: list[LineItem], clinical: list[str], policy: Policy
) -> tuple[bool, str]:
    if rules.requires_pre_auth:
        return True, f"Policy requires pre-authorization for {claim.claim_category.value} claims."
    threshold = rules.pre_auth_threshold
    known_tests = rules.high_value_tests_requiring_pre_auth
    if known_tests and threshold:
        for li in line_items:
            test = _line_high_value_test(li, policy, known_tests)
            if test and li.amount > threshold:
                return True, f"'{li.description}' ({test}, ₹{li.amount:,.0f}) is a high-value test requiring pre-authorization above ₹{threshold:,.0f}."
        ordered = [test for text in clinical if (test := match_high_value_test(policy, text)) is not None]
        if any(t in known_tests for t in ordered) and claim.claimed_amount > threshold:
            return True, f"A high-value test was ordered and the claimed amount ₹{claim.claimed_amount:,.0f} exceeds ₹{threshold:,.0f}."
    return False, ""


def _adjudicate_line_items(
    category: ClaimCategory, rules, line_items: list[LineItem], trace: TraceRecorder
) -> list[LineItem]:
    covered = [normalize(p) for p in rules.covered_procedures + rules.covered_items]
    excluded = [normalize(p) for p in rules.excluded_procedures + rules.excluded_items]
    if not covered and not excluded:
        for li in line_items:
            li.status = LineItemStatus.APPROVED
            li.approved_amount = li.amount
        return line_items

    for li in line_items:
        if li.matched_policy_item:
            is_excluded = normalize(li.matched_policy_item) in excluded
        else:
            desc = normalize(li.description)
            # Word-boundary match (same as tagging/network) — avoid accidental
            # substring hits across unrelated procedure names.
            is_excluded = any(
                e and (contains_normalized(desc, e) or contains_normalized(e, desc))
                for e in excluded
            )
        if is_excluded:
            li.status = LineItemStatus.REJECTED
            li.approved_amount = 0
            li.rejection_reason = (
                f"'{li.description}' is in the policy's excluded "
                f"{category.value.lower()} procedures list."
            )
            trace.check(
                COMPONENT,
                False,
                f"Line item rejected: '{li.description}' ₹{li.amount:,.0f} — {li.rejection_reason}",
                li.model_dump(),
            )
        else:
            li.status = LineItemStatus.APPROVED
            li.approved_amount = li.amount
            trace.check(
                COMPONENT,
                True,
                f"Line item approved: '{li.description}' ₹{li.amount:,.0f}.",
                li.model_dump(),
            )
    return line_items


def _line_is_consultation(li: LineItem, policy: Policy) -> bool:
    if li.is_consultation_fee is not None:
        return li.is_consultation_fee
    return is_consultation_fee(policy, li.description)


def _sub_limit_base(category: ClaimCategory, line_items: list[LineItem], eligible: float, policy: Policy) -> float:
    if category == ClaimCategory.CONSULTATION and line_items:
        consultation_portion = sum(li.amount for li in line_items if li.status == LineItemStatus.APPROVED and _line_is_consultation(li, policy))
        return consultation_portion if consultation_portion > 0 else eligible
    return eligible
