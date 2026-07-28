"""Claim resume (HITL) request body."""

from typing import Literal

from pydantic import BaseModel, Field


class ResumeClaimRequest(BaseModel):
    action: Literal["approve", "reject"] = Field(
        ..., description="Ops action for a claim paused at MANUAL_REVIEW"
    )
    note: str | None = Field(default=None, description="Optional ops note for the audit trail")
