"""MemberMessagePolisher: warm prose for the member, facts unchanged.

The decision and every figure in it come from deterministic code; the ONLY
thing delegated to the LLM is phrasing. Safety rails:

  - the model receives the template message and rewrites style, not content;
  - every number in the template (amounts, dates, percentages) must appear
    verbatim in the rewrite, or the template is used instead;
  - any LLM failure falls back to the template silently.

Without an LLM client (evals, simulation), the template is used as-is.
"""

import re

from pydantic import BaseModel, Field

from app.llm.client import LlmClient
from app.llm.prompts import MEMBER_MESSAGE_PROMPT
from app.observability.langsmith import traceable
from app.observability.trace import TraceRecorder

COMPONENT = "MemberMessagePolisher"

_NUMBER_RE = re.compile(r"₹[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?%|\d{4}-\d{2}-\d{2}")


class LlmMemberMessage(BaseModel):
    """Structured output for the polish pass."""

    message: str = Field(..., description="The rewritten member-facing message")


@traceable(
    name="MemberMessagePolish",
    run_type="chain",
    process_inputs=lambda inputs: {"template_preview": (inputs.get("template") or "")[:240]},
)
def polish_member_message(
    template: str, llm: LlmClient | None, trace: TraceRecorder
) -> str:
    """Return a warmer version of `template`, or the template itself.

    Fidelity check: every figure in the template must survive verbatim —
    a rewrite that drops or alters a number is rejected.
    """
    if llm is None:
        return template
    out = llm.structured(
        LlmMemberMessage, MEMBER_MESSAGE_PROMPT.format(template_message=template)
    )
    polished = out.message.strip()
    required_figures = set(_NUMBER_RE.findall(template))
    if polished and required_figures.issubset(set(_NUMBER_RE.findall(polished))):
        trace.info(COMPONENT, "Member message polished (all figures preserved verbatim).")
        return polished
    trace.warn(
        COMPONENT,
        "Polished message dropped or altered a figure — template message kept.",
    )
    return template
