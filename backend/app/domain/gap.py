from enum import Enum

from pydantic import BaseModel, Field


class GapVerdict(str, Enum):
    retry = "retry"
    leave = "leave"


class GapDecision(BaseModel):
    field: str
    verdict: GapVerdict
    reason: str
    related_supported: list[str] = Field(default_factory=list)
    retried: bool = False
    left_missing: bool = False
    tool_name: str | None = None
    focus: str | None = None
