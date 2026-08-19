"""WBS 生成 JSON 形状（Pydantic）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WbsTaskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    start_date: str
    end_date: str
    description: str | None = Field(default=None, max_length=2000)
    depends_on: list[str] | None = Field(default=None, max_length=20)


class WbsMilestoneOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    start_date: str
    end_date: str
    tasks: list[WbsTaskOut] = Field(min_length=1, max_length=40)


class DayAssignmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    task_codes: list[str] = Field(min_length=1, max_length=1)

    @field_validator("task_codes")
    @classmethod
    def _exactly_one_code(cls, v: list[str]) -> list[str]:
        if len(v) != 1:
            raise ValueError("每天恰好一件任务，task_codes 长度必须为 1")
        return v


class WbsGeneratePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestones: list[WbsMilestoneOut] = Field(min_length=1, max_length=20)
    day_assignments: list[DayAssignmentOut] = Field(min_length=1)
    assumptions: list[str] | None = Field(default=None, max_length=20)
    risks: list[str] | None = Field(default=None, max_length=20)
    suggested_deadline_change: str | None = None
