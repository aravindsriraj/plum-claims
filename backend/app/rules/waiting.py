"""Waiting-period rules: initial and condition-specific.

All date math is plain `datetime` on policy-provided day counts. Every check
reports the date from which the member WILL be eligible — the assignment
(TC005) requires the rejection message to state exactly that.
"""

from datetime import date, timedelta

from pydantic import BaseModel


class WaitingPeriodResult(BaseModel):
    check_name: str
    applies: bool = True  # False -> condition not present, check not relevant
    passed: bool = True
    eligible_from: date | None = None
    days_waiting: int = 0
    condition: str | None = None
    reason: str = ""


def _evaluate_wait(
    join_date: date,
    treatment_date: date,
    waiting_days: int,
    *,
    check_name: str,
    condition: str | None = None,
    passed_reason: str,
    failed_reason: str,
) -> WaitingPeriodResult:
    eligible_from = join_date + timedelta(days=waiting_days)
    passed = treatment_date >= eligible_from
    return WaitingPeriodResult(
        check_name=check_name,
        condition=condition,
        passed=passed,
        eligible_from=eligible_from,
        days_waiting=waiting_days,
        reason=passed_reason.format(eligible_from=eligible_from.isoformat())
        if passed
        else failed_reason.format(eligible_from=eligible_from.isoformat()),
    )


def check_initial_waiting_period(
    join_date: date, treatment_date: date, waiting_days: int
) -> WaitingPeriodResult:
    """The blanket waiting period every member serves from their join date."""
    treatment = treatment_date.isoformat()
    return _evaluate_wait(
        join_date,
        treatment_date,
        waiting_days,
        check_name="INITIAL_WAITING_PERIOD",
        passed_reason=(
            f"Treatment date {treatment} is on/after the end of the "
            f"{waiting_days}-day initial waiting period ({{eligible_from}})."
        ),
        failed_reason=(
            f"Treatment date {treatment} falls within the "
            f"{waiting_days}-day initial waiting period. Eligible from {{eligible_from}}."
        ),
    )


def check_specific_waiting_periods(
    join_date: date,
    treatment_date: date,
    matched_conditions: list[str],
    specific_conditions_days: dict[str, int],
) -> list[WaitingPeriodResult]:
    """One result per matched condition that has a policy waiting period."""
    results: list[WaitingPeriodResult] = []
    treatment = treatment_date.isoformat()
    for condition in matched_conditions:
        waiting_days = specific_conditions_days.get(condition)
        if waiting_days is None:
            continue
        results.append(
            _evaluate_wait(
                join_date,
                treatment_date,
                waiting_days,
                check_name=f"SPECIFIC_WAITING_PERIOD[{condition}]",
                condition=condition,
                passed_reason=(
                    f"{condition}: treatment on {treatment} is on/after the "
                    f"{waiting_days}-day waiting period end ({{eligible_from}})."
                ),
                failed_reason=(
                    f"{condition}: {waiting_days}-day waiting period not served. "
                    f"Eligible from {{eligible_from}}."
                ),
            )
        )
    return results
