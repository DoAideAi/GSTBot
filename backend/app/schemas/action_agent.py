"""The agent can recommend only existing workspace destinations."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.gst_calendar import PERIOD_PATTERN

Source = Literal["overview", "reconciliation", "invoice_checks"]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern=PERIOD_PATTERN)
    focus: Literal["all", "itc", "filing"] = "all"


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    priority: Literal["high", "medium", "low"]
    reason: str = Field(min_length=1, max_length=600)
    next_step: str = Field(min_length=1, max_length=400)
    destination: Literal["invoices", "upload", "reconcile", "itc", "filing", "alerts"]
    sources: list[Source] = Field(min_length=1, max_length=3)


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=700)
    actions: list[Action] = Field(min_length=1, max_length=5)
    caveats: list[str] = Field(max_length=3)


class ReviewOut(BaseModel):
    period: str
    generated_at: datetime
    plan: ActionPlan
    checked: list[Source]
    facts: dict
