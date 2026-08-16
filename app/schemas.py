from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class WechatLoginIn(BaseModel):
    code: str


class UserOut(BaseModel):
    id: int
    nickname: str | None
    avatar_url: str | None
    timezone: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut


class GoalCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    plan_start_date: date
    plan_end_date: date
    note: str | None = None


class GoalPatchIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = None


class PlanEditIn(BaseModel):
    new_plan_end_date: date | None = None
    note: str | None = None


class IncompleteIn(BaseModel):
    incomplete_reason: str = Field(min_length=1, max_length=500)


class ConfirmWbsIn(BaseModel):
    nodes: list | None = None
    day_assignments: list | None = None


class DeadlineChangeIn(BaseModel):
    new_plan_end_date: date


class InternalRunIn(BaseModel):
    as_of: datetime | None = None
