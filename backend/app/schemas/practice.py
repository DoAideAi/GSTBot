from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterCommit(StrictRequest):
    skip_invalid: bool = False
    save_mapping_name: str | None = Field(default=None, min_length=1, max_length=80)


class InviteCreate(StrictRequest):
    email: EmailStr
    role: Literal["accountant", "viewer"]


class InviteToken(StrictRequest):
    token: str = Field(min_length=40, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class MemberRoleChange(StrictRequest):
    role: Literal["accountant", "viewer"]


class FindingReviewUpdate(StrictRequest):
    version: int = Field(ge=0)
    status: Literal["open", "in_review", "resolved"]
    decision: Literal["none", "accept_match", "reject_match", "follow_up"]
    assignee_id: int | None = Field(default=None, ge=1, le=2147483647)
    note: str = Field(default="", max_length=2000)


class ClientQueueItem(BaseModel):
    id: int
    name: str
    gstin: str | None
    purchase_count: int
    has_2b: bool
    run_id: int | None
    unresolved: int | None
    stale: bool
    reviewed: bool
    exported: bool
    next_action: str


class ClientQueueOut(BaseModel):
    items: list[ClientQueueItem]
    period: str
    total: int
    limit: int
    offset: int
