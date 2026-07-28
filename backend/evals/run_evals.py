"""Eval runner: executes all 12 test cases through the real pipeline and
writes docs/EVAL_REPORT.md.

Usage:  .venv/bin/python -m evals.run_evals

Pass criteria are derived from each case's `expected` block:
  - decision matches (or status=DOCUMENT_REJECTED when expected.decision is null)
  - approved_amount matches when specified
  - rejection_reasons match when specified
  - confidence thresholds ("above 0.85") when specified
  - system_must items that are mechanically checkable

The runner uses NO LLM (provided-content/metadata modes only), so the report
is deterministic and reproducible.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.enums import ClaimStatus  # noqa: E402
from app.contracts.inputs import ClaimInput  # noqa: E402
from app.policy.loader import load_policy  # noqa: E402
from app.service import ClaimService  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT.parents[0] / "docs" / "EVAL_REPORT.md"


def check_case(case: dict, response) -> list[str]:
    """Return a list of failed assertions (empty = pass)."""
    failures: list[str] = []
    expected = case["expected"]
    exp_decision = expected.get("decision")

    if exp_decision is None:
        if response.status != ClaimStatus.DOCUMENT_REJECTED:
            failures.append(
                f"expected early stop (DOCUMENT_REJECTED), got {response.status.value}"
            )
        elif not response.document_issues:
            failures.append("expected document_issues to be non-empty")
        else:
            joined = " ".join(i.message for i in response.document_issues).lower()
            if "please" not in joined and "upload" not in joined:
                failures.append("member message does not appear actionable")
    else:
        actual = response.decision.decision.value if response.decision else None
        if actual != exp_decision:
            failures.append(f"expected decision {exp_decision}, got {actual}")

        if "approved_amount" in expected and response.decision:
            if abs(response.decision.approved_amount - expected["approved_amount"]) > 0.01:
                failures.append(
                    f"expected approved_amount {expected['approved_amount']}, "
                    f"got {response.decision.approved_amount}"
                )

        if "rejection_reasons" in expected and response.decision:
            if set(response.decision.rejection_reasons) != set(expected["rejection_reasons"]):
                failures.append(
                    f"expected rejection_reasons {expected['rejection_reasons']}, "
                    f"got {response.decision.rejection_reasons}"
                )

        if "confidence_score" in expected and response.decision:
            threshold = float(expected["confidence_score"].replace("above", "").strip())
            if not response.decision.confidence_score > threshold:
                failures.append(
                    f"expected confidence above {threshold}, "
                    f"got {response.decision.confidence_score}"
                )

        # Mechanically checkable system_must items.
        musts = expected.get("system_must", [])
        if any("confidence score lower" in m for m in musts):
            if response.decision and response.decision.confidence_score >= 0.90:
                failures.append(
                    f"degraded-run confidence {response.decision.confidence_score} "
                    f"is not lower than a normal approval"
                )
        if any("component failed and was skipped" in m for m in musts):
            if not (response.decision and response.decision.degraded):
                failures.append("output does not indicate a component failure")
        if any("manual review is recommended" in m.lower() for m in musts):
            notes = " ".join(response.decision.notes).lower() if response.decision else ""
            if "manual review" not in notes or "recommend" not in notes:
                failures.append("missing manual-review recommendation note")
        if any("not crash" in m for m in musts):
            pass  # reaching this line is the assertion
        if any("specific signals" in m for m in musts):
            if not (response.decision and response.decision.fraud_signals):
                failures.append("no fraud signals included in output")

    return failures


def render_report(results: list[dict]) -> str:
    passed = sum(1 for r in results if not r["failures"])
    lines = [
        "# Eval Report — 12 Test Cases",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}  ",
        f"Result: **{passed}/{len(results)} passed** (deterministic run, no LLM calls — "
        f"documents use provided-content/metadata modes)",
        "",
        "| Case | Name | Expected | Actual | Result |",
        "|------|------|----------|--------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r['case_id']} | {r['case_name']} | {r['expected']} | {r['actual']} "
            f"| {'PASS' if not r['failures'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in results:
        resp = r["response"]
        lines.append(f"## {r['case_id']} — {r['case_name']}")
        lines.append("")
        lines.append(f"**{r['case_description']}**")
        lines.append("")
        lines.append(f"- Status: `{resp.status.value}`")
        if resp.decision:
            d = resp.decision
            lines.append(
                f"- Decision: `{d.decision.value}`, approved ₹{d.approved_amount:,.0f} "
                f"of ₹{d.claimed_amount:,.0f}, confidence {d.confidence_score:.2f}"
            )
            if d.rejection_reasons:
                lines.append(f"- Rejection reasons: {d.rejection_reasons}")
            if d.fraud_signals:
                lines.append(f"- Fraud signals: {[s.code for s in d.fraud_signals]}")
            if d.degraded:
                lines.append(
                    f"- Degraded: YES — failures: "
                    f"{[f.component for f in d.component_failures]}"
                )
            if d.notes:
                lines.append(f"- Notes: {d.notes}")
        else:
            lines.append("- Member-facing issues:")
            for i in resp.document_issues:
                lines.append(f"  - [{i.code.value}] {i.message}")
        if r["failures"]:
            lines.append("")
            lines.append(f"**FAILURES:** {'; '.join(r['failures'])}")
        lines.append("")
        lines.append("<details><summary>Full trace</summary>")
        lines.append("")
        lines.append("```")
        lines.append(resp.explanation)
        lines.append("```")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    cases = json.loads((ROOT / "data" / "test_cases.json").read_text())["test_cases"]
    service = ClaimService(load_policy(), llm=None)

    results = []
    for case in cases:
        claim = ClaimInput(**case["input"])
        response = service.process(claim)
        failures = check_case(case, response)
        actual = (
            response.decision.decision.value
            if response.decision
            else response.status.value
        )
        results.append(
            {
                "case_id": case["case_id"],
                "case_name": case["case_name"],
                "case_description": case["description"],
                "expected": case["expected"].get("decision") or "EARLY_STOP",
                "actual": actual,
                "failures": failures,
                "response": response,
            }
        )
        mark = "PASS" if not failures else "FAIL"
        print(f"{case['case_id']} {case['case_name']:<45} {mark}  ({actual})")
        for f in failures:
            print(f"    - {f}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(results), encoding="utf-8")
    passed = sum(1 for r in results if not r["failures"])
    print(f"\n{passed}/{len(results)} passed. Report: {REPORT_PATH}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
