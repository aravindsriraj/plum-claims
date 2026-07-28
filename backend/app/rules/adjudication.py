"""AdjudicationEngine: deterministic policy evaluation.

Every rule here reads its parameters from the loaded Policy object (i.e. from
policy_terms.json). No coverage logic is hardcoded; only the ENGINE (which
checks exist and in what order) lives in code.

Rule order, with rationale:
  1. Member validity          — can't cover someone not on the roster
  2. Submission deadline      — only when submission_date is provided
  3. Minimum claim amount     — cheap sanity gate
  4. Initial waiting period   — blanket gate before anything clinical
  5. Exclusions               — an excluded condition is NEVER payable, so it
                                short-circuits all remaining hard checks
                                (TC012: only EXCLUDED_CONDITION is reported)
  6. Specific waiting periods — condition-level gates (TC005)
  7. Pre-authorization        — fires before amount rules (TC007 expects
                                PRE_AUTH_MISSING, not PER_CLAIM_EXCEEDED)
  8. Per-claim limit          — (TC008)
  9. Line-item adjudication   — covered vs excluded procedures (TC006)
 10. Financial computation    — sub-limit -> network discount -> co-pay
                                (TC004, TC010)

Hard-fail checks short-circuit: once a claim is definitively not payable,
later hard checks are recorded as SKIPPED so the trace stays honest about
what was and wasn't evaluated.
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
from app.rules.tagging import tag_deterministic
from app.rules.textnorm import normalize
from app.rules.waiting import (
    check_initial_waiting_period,
    check_specific_waiting_periods,
)
from app.util import parse_iso_date

COMPONENT = "AdjudicationEngine"


def _clinical_texts(docs: list[ExtractedDocument]) -> list[str]:
    """All clinical free-text across documents: diagnosis, treatment, tests."""
    texts: list[str] = []
    for d in docs:
        texts.extend(t for t in (d.diagnosis, d.treatment) if t)
        texts.extend(d.tests_ordered)
    return texts


def _all_line_items(docs: list[ExtractedDocument]) -> list[LineItem]:
    """Line items from billing documents, copied so adjudication can annotate."""
    items: list[LineItem] = []
    for d in docs:
        for li in d.line_items:
            items.append(li.model_copy())
    return items


def _tags_for(docs: list[ExtractedDocument], policy: Policy) -> DocumentTags:
    """Aggregate semantic tags across all documents.

    The ExtractionAgent tags every document it produces (deterministically in
    provided-content mode, LLM+deterministic union in vision mode). Documents
    built outside the pipeline (unit tests, direct API construction) may be
    untagged — those are tagged deterministically here so the rule engine
    NEVER matches raw text itself; it only consumes tags.
    """
    conditions: list[str] = []
    exclusions: list[PolicyTag] = []
    seen_exclusions: set[str] = set()
    for d in docs:
        tags = d.tags
        if tags is None:
            tags = tag_deterministic(policy, d.diagnosis, d.treatment, *d.tests_ordered)
        for c in tags.conditions:
            if c not in conditions:
                conditions.append(c)
        for tag in tags.exclusions:
            if tag.entry not in seen_exclusions:
                seen_exclusions.add(tag.entry)
                exclusions.append(tag)
    return DocumentTags(conditions=conditions, exclusions=exclusions)


def _provider_name(claim: ClaimInput, docs: list[ExtractedDocument]) -> str | None:
    """Provider name for network-discount purposes.

    Documents (the bill's letterhead) are evidence and win over the claim
    form; the form's hospital_name is a hint used only when no document
    carries a provider. Any disagreement between the two is flagged by the
    CrossValidationAgent.
    """
    for d in docs:
        if d.provider_name:
            return d.provider_name
    return claim.hospital_name


def adjudicate(
    claim: ClaimInput,
    policy: Policy,
    docs: list[ExtractedDocument],
    trace: TraceRecorder,
) -> AdjudicationResult:
    """Run all policy rules for a claim. Never raises on rule logic — every
    outcome, pass or fail, is recorded in the trace."""
    result = AdjudicationResult()
    rules = policy.category_rules(claim.claim_category)
    clinical = _clinical_texts(docs)
    line_items = _all_line_items(docs)
    tags = _tags_for(docs, policy)

    def add_check(check: RuleCheck) -> bool:
        """Record a check and return whether the pipeline may continue."""
        result.checks.append(check)
        trace.check(COMPONENT, check.passed, f"{check.name}: {check.reason}", check.detail)
        if check.hard_fail and not check.passed:
            result.rejection_reasons.append(check.rule_id)
            return False
        return True

    def skip_remaining(reason: str) -> None:
        trace.skipped(COMPONENT, reason)

    # --- 1. Member validity -------------------------------------------------
    member = policy.find_member(claim.member_id)
    if not add_check(
        RuleCheck(
            rule_id="MEMBER_NOT_FOUND",
            name="Member validity",
            passed=member is not None,
            hard_fail=True,
            reason=(
                f"Member {claim.member_id} found in policy roster."
                if member
                else f"Member {claim.member_id} is not on the policy roster."
            ),
            detail={"member_id": claim.member_id},
        )
    ):
        return result
    join_date = parse_iso_date(policy.member_join_date(member))

    # --- 1b. Category coverage gate ------------------------------------------
    # The policy can turn an entire category off (covered: false). Check this
    # before anything else clinical — an uncovered category is never payable.
    if not add_check(
        RuleCheck(
            rule_id="CATEGORY_NOT_COVERED",
            name="Category coverage",
            passed=rules.covered,
            hard_fail=True,
            reason=(
                f"{claim.claim_category.value} is a covered category under this policy."
                if rules.covered
                else f"{claim.claim_category.value} is not covered under this policy."
            ),
            detail={"category": claim.claim_category.value, "covered": rules.covered},
        )
    ):
        return result

    # --- 2. Submission deadline (only when submission_date is provided) -----
    if claim.submission_date:
        deadline_days = policy.submission_deadline_days
        days_late = (claim.submission_date - claim.treatment_date).days
        if not add_check(
            RuleCheck(
                rule_id="SUBMISSION_DEADLINE_MISSED",
                name="Submission deadline",
                passed=days_late <= deadline_days,
                hard_fail=True,
                reason=(
                    f"Submitted {days_late} days after treatment (limit {deadline_days})."
                ),
                detail={"days_after_treatment": days_late, "limit": deadline_days},
            )
        ):
            return result
    else:
        trace.skipped(
            COMPONENT,
            "Submission deadline: NOT_EVALUATED (no submission_date provided).",
        )

    # --- 3. Minimum claim amount --------------------------------------------
    minimum = policy.minimum_claim_amount
    if not add_check(
        RuleCheck(
            rule_id="BELOW_MINIMUM_AMOUNT",
            name="Minimum claim amount",
            passed=claim.claimed_amount >= minimum,
            hard_fail=True,
            reason=(
                f"Claimed ₹{claim.claimed_amount:,.0f} meets the minimum of ₹{minimum:,.0f}."
                if claim.claimed_amount >= minimum
                else f"Claimed ₹{claim.claimed_amount:,.0f} is below the minimum "
                f"claim amount of ₹{minimum:,.0f}."
            ),
            detail={"claimed": claim.claimed_amount, "minimum": minimum},
        )
    ):
        return result

    # --- 4. Initial waiting period -------------------------------------------
    if join_date:
        initial = check_initial_waiting_period(
            join_date, claim.treatment_date, policy.initial_waiting_period_days
        )
        if not add_check(
            RuleCheck(
                rule_id="WAITING_PERIOD",
                name="Initial waiting period",
                passed=initial.passed,
                hard_fail=True,
                reason=initial.reason,
                detail={
                    "join_date": join_date.isoformat(),
                    "eligible_from": initial.eligible_from.isoformat(),
                },
            )
        ):
            return result
    else:
        trace.skipped(
            COMPONENT,
            "Initial waiting period: NOT_EVALUATED (member join date unavailable).",
        )

    # --- 5. Exclusions (short-circuits everything) ---------------------------
    # Tags, not raw text: extraction mapped the clinical content onto the
    # policy's exclusion vocabulary; the engine only consumes that mapping.
    exclusion_matches = tags.exclusions
    if exclusion_matches:
        matched = exclusion_matches[0]
        add_check(
            RuleCheck(
                rule_id="EXCLUDED_CONDITION",
                name="Policy exclusions",
                passed=False,
                hard_fail=True,
                reason=(
                    f"Treatment relates to '{matched.matched_text}', which falls under "
                    f"the policy exclusion '{matched.entry}'. Excluded conditions "
                    f"are never payable under this policy."
                ),
                detail={
                    "policy_entry": matched.entry,
                    "matched_text": matched.matched_text,
                    "via": matched.via,
                    "all_matches": [m.entry for m in exclusion_matches],
                },
            )
        )
        skip_remaining(
            "Claim excluded — remaining hard checks not evaluated "
            "(an excluded condition is never payable)."
        )
        return result
    add_check(
        RuleCheck(
            rule_id="EXCLUDED_CONDITION",
            name="Policy exclusions",
            passed=True,
            reason="No policy exclusion matches the diagnosis/treatment.",
            detail={"clinical_texts_reviewed": clinical},
        )
    )

    # --- 6. Specific-condition waiting periods --------------------------------
    matched_conditions = tags.conditions
    if join_date and matched_conditions:
        waiting_results = check_specific_waiting_periods(
            join_date,
            claim.treatment_date,
            matched_conditions,
            policy.specific_condition_waiting_days,
        )
        for wr in waiting_results:
            if not add_check(
                RuleCheck(
                    rule_id="WAITING_PERIOD",
                    name=f"Waiting period — {wr.condition}",
                    passed=wr.passed,
                    hard_fail=True,
                    reason=wr.reason,
                    detail={
                        "condition": wr.condition,
                        "waiting_days": wr.days_waiting,
                        "eligible_from": wr.eligible_from.isoformat(),
                    },
                )
            ):
                return result
    else:
        trace.skipped(
            COMPONENT,
            "Specific waiting periods: no waiting-listed condition detected "
            f"(conditions checked: {matched_conditions or 'none matched'}).",
        )

    # --- 7. Pre-authorization --------------------------------------------------
    pre_auth_needed, pre_auth_why = _pre_auth_requirement(
        claim, rules, line_items, clinical
    )
    if pre_auth_needed:
        if not add_check(
            RuleCheck(
                rule_id="PRE_AUTH_MISSING",
                name="Pre-authorization",
                passed=claim.pre_auth_reference is not None,
                hard_fail=True,
                reason=(
                    f"Pre-authorization obtained (ref {claim.pre_auth_reference})."
                    if claim.pre_auth_reference
                    else f"{pre_auth_why} No pre-authorization reference was submitted. "
                    f"The member should obtain pre-authorization from the insurer and "
                    f"resubmit the claim with the pre-auth reference number."
                ),
                detail={"requirement": pre_auth_why},
            )
        ):
            return result
    else:
        add_check(
            RuleCheck(
                rule_id="PRE_AUTH_MISSING",
                name="Pre-authorization",
                passed=True,
                reason="No pre-authorization required for this claim.",
            )
        )

    # --- 8. Per-claim limit ------------------------------------------------------
    # Interpretation (documented in ARCHITECTURE.md): the blanket per-claim
    # limit governs CONSULTATION (general OPD) claims. Specialized categories
    # (dental, vision, pharmacy, ...) are bounded by their own category
    # sub-limits instead — this is the only reading consistent with the
    # policy's category sub-limits exceeding the per-claim figure.
    per_claim_limit = policy.per_claim_limit
    applies = claim.claim_category == ClaimCategory.CONSULTATION
    if not applies:
        trace.skipped(
            COMPONENT,
            f"Per-claim limit: governs CONSULTATION claims; "
            f"{claim.claim_category.value} is bounded by its category sub-limit "
            f"(₹{rules.sub_limit:,.0f}).",
        )
    if applies and not add_check(
        RuleCheck(
            rule_id="PER_CLAIM_EXCEEDED",
            name="Per-claim limit",
            passed=claim.claimed_amount <= per_claim_limit,
            hard_fail=True,
            reason=(
                f"Claimed ₹{claim.claimed_amount:,.0f} is within the per-claim "
                f"limit of ₹{per_claim_limit:,.0f}."
                if claim.claimed_amount <= per_claim_limit
                else f"Claimed amount ₹{claim.claimed_amount:,.0f} exceeds the "
                f"per-claim limit of ₹{per_claim_limit:,.0f}."
            ),
            detail={"claimed": claim.claimed_amount, "per_claim_limit": per_claim_limit},
        )
    ):
        return result

    # --- 9. Line-item adjudication ----------------------------------------------
    line_items = _adjudicate_line_items(claim.claim_category, rules, line_items, trace)
    result.line_items = line_items
    eligible = sum(li.amount for li in line_items if li.status == LineItemStatus.APPROVED)
    # Bills without itemization: fall back to the claimed amount as eligible.
    if not line_items:
        eligible = claim.claimed_amount
    result.eligible_amount = round(eligible, 2)

    if line_items and eligible == 0:
        add_check(
            RuleCheck(
                rule_id="NO_ELIGIBLE_LINE_ITEMS",
                name="Eligible line items",
                passed=False,
                hard_fail=True,
                reason="Every billed line item is excluded under the policy.",
            )
        )
        return result

    # --- 10. Financial computation ------------------------------------------------
    provider = _provider_name(claim, docs)
    # Step A: sub-limit. For consultation claims it caps only the
    # consultation-fee portion; for single-service categories it caps the
    # whole eligible amount.
    sub_limit_base = _sub_limit_base(claim.claim_category, line_items, eligible)
    remainder = eligible - sub_limit_base
    capped_base, sub_adj = apply_sub_limit(sub_limit_base, claim.claim_category.value, rules)
    eligible_after_cap = round(capped_base + remainder, 2)
    if sub_adj:
        result.adjustments.append(sub_adj)

    # Step B: network discount, THEN co-pay, on the full post-cap amount.
    # This ordering is contractual (TC010): discount before co-pay.
    network = is_network_hospital(provider, policy.network_hospitals)
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
        trace.info(
            COMPONENT,
            f"{adj.kind.value}: ₹{adj.amount_before:,.0f} -> ₹{adj.amount_after:,.0f}. {adj.note}",
            adj.model_dump(),
        )
    trace.info(
        COMPONENT,
        f"Financial summary: eligible ₹{result.eligible_amount:,.0f} -> "
        f"approved ₹{result.approved_amount:,.0f}.",
    )
    return result


def _pre_auth_requirement(
    claim: ClaimInput,
    rules,
    line_items: list[LineItem],
    clinical: list[str],
) -> tuple[bool, str]:
    """Decide whether this claim needed pre-authorization, and why."""
    if rules.requires_pre_auth:
        return True, f"Policy requires pre-authorization for {claim.claim_category.value} claims."

    # High-value diagnostics: named test above the category threshold.
    threshold = rules.pre_auth_threshold
    if rules.high_value_tests_requiring_pre_auth and threshold:
        billed_high_value = [
            li
            for li in line_items
            if any(
                normalize(t) in normalize(li.description)
                for t in rules.high_value_tests_requiring_pre_auth
            )
        ]
        for li in billed_high_value:
            if li.amount > threshold:
                return True, (
                    f"'{li.description}' (₹{li.amount:,.0f}) is a high-value test "
                    f"requiring pre-authorization above ₹{threshold:,.0f}."
                )
        # Test ordered but above-threshold claim with no itemized bill.
        if any(
            normalize(t) in normalize(text)
            for t in rules.high_value_tests_requiring_pre_auth
            for text in clinical
        ) and claim.claimed_amount > threshold:
            return True, (
                f"A high-value test was ordered and the claimed amount "
                f"₹{claim.claimed_amount:,.0f} exceeds ₹{threshold:,.0f}."
            )
    return False, ""


def _adjudicate_line_items(
    category: ClaimCategory,
    rules,
    line_items: list[LineItem],
    trace: TraceRecorder,
) -> list[LineItem]:
    """Approve/reject each line item against the category's procedure lists.

    Only categories with explicit covered/excluded procedure lists (dental,
    vision) adjudicate per item; other categories treat all items as eligible
    (claim-level exclusions have already run by this point).

    Matching: an item tagged by extraction (matched_policy_item — a verbatim
    policy procedure) is judged by exact membership; untagged items fall back
    to normalized containment against the policy lists.
    """
    covered = [normalize(p) for p in rules.covered_procedures + rules.covered_items]
    excluded = [normalize(p) for p in rules.excluded_procedures + rules.excluded_items]
    if not covered and not excluded:
        for li in line_items:
            li.status = LineItemStatus.APPROVED
            li.approved_amount = li.amount
        return line_items

    for li in line_items:
        if li.matched_policy_item:
            # Tagged by extraction: the tag IS the policy entry — exact check.
            is_excluded = normalize(li.matched_policy_item) in excluded
        else:
            desc = normalize(li.description)
            is_excluded = any(e and (e in desc or desc in e) for e in excluded)
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


def _sub_limit_base(
    category: ClaimCategory, line_items: list[LineItem], eligible: float
) -> float:
    """The amount the category sub-limit applies to.

    CONSULTATION claims often bundle non-consultation items (tests, medicines);
    the consultation sub-limit caps only the consultation-fee portion. For
    single-service categories the sub-limit applies to the full eligible amount.
    """
    if category == ClaimCategory.CONSULTATION and line_items:
        consultation_portion = sum(
            li.amount
            for li in line_items
            if li.status == LineItemStatus.APPROVED and "consultation" in normalize(li.description)
        )
        # If nothing is labelled 'consultation', the whole claim is treated as consult.
        return consultation_portion if consultation_portion > 0 else eligible
    return eligible
