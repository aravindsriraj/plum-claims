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


def check_initial_waiting_period(
    join_date: date, treatment_date: date, waiting_days: int
) -> WaitingPeriodResult:
    """The blanket waiting period every member serves from their join date."""
    eligible_from = join_date + timedelta(days=waiting_days)
    passed = treatment_date >= eligible_from
    return WaitingPeriodResult(
        check_name="INITIAL_WAITING_PERIOD",
        passed=passed,
        eligible_from=eligible_from,
        days_waiting=waiting_days,
        reason=(
            f"Treatment date {treatment_date.isoformat()} is on/after the end of the "
            f"{waiting_days}-day initial waiting period ({eligible_from.isoformat()})."
            if passed
            else f"Treatment date {treatment_date.isoformat()} falls within the "
            f"{waiting_days}-day initial waiting period. Eligible from {eligible_from.isoformat()}."
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
    for condition in matched_conditions:
        waiting_days = specific_conditions_days.get(condition)
        if waiting_days is None:
            continue  # condition has no specific waiting period in this policy
        eligible_from = join_date + timedelta(days=waiting_days)
        passed = treatment_date >= eligible_from
        results.append(
            WaitingPeriodResult(
                check_name=f"SPECIFIC_WAITING_PERIOD[{condition}]",
                condition=condition,
                passed=passed,
                eligible_from=eligible_from,
                days_waiting=waiting_days,
                reason=(
                    f"{condition}: treatment on {treatment_date.isoformat()} is on/after the "
                    f"{waiting_days}-day waiting period end ({eligible_from.isoformat()})."
                    if passed
                    else f"{condition}: {waiting_days}-day waiting period not served. "
                    f"Eligible from {eligible_from.isoformat()}."
                ),
            )
        )
    return results
