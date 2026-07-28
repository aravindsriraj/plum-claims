"""LLM client: the only module allowed to talk to a model.

Design rules for the whole codebase:
  - LLMs are used for PERCEPTION only (classifying documents, reading messy
    images, semantic matching). All judgment — math, dates, limits, decisions —
    is deterministic code in app/rules/.
  - Every LLM call returns a Pydantic-validated object via structured output.
    Invalid/unparseable output raises and is retried, then surfaced to the
    resilience wrapper — it never silently propagates.
"""

import os
from typing import TypeVar

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
# Hard ceiling per call so a hung model degrades the claim instead of the request.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))


class LlmClient:
    """Thin wrapper over ChatGoogleGenerativeAI with vision + structured output.

    `call_count` lets the pipeline report how many LLM calls a claim needed
    (surfaced in ProcessingMeta — a cheap but honest cost signal).
    """

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._chat = ChatGoogleGenerativeAI(
            model=model,
            temperature=0,  # perception tasks want determinism, not creativity
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        self.call_count = 0

    def structured(
        self,
        schema: type[T],
        prompt: str,
        image_base64: str | None = None,
        mime_type: str = "image/jpeg",
    ) -> T:
        """Call the model and return a validated `schema` instance.

        Pass `image_base64` for vision tasks (document classification /
        extraction from real uploads). Raises on validation failure or
        timeout — callers are expected to wrap with run_resilient().
        """
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_base64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                }
            )
        self.call_count += 1
        return self._chat.with_structured_output(schema).invoke(
            [HumanMessage(content=content)]
        )
