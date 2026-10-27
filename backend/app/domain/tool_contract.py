from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.collected_research import CollectedResearch
from app.domain.evidence import EvidenceItem


class DocumentInput(BaseModel):
    filename: str
    text: str | None = None
    raw_bytes: bytes | None = None


class ToolRequest(BaseModel):
    company_name: str
    company_domain: str | None = None
    website_url: str | None = None
    documents: list[DocumentInput] = Field(default_factory=list)
    focus: str | None = None


class ToolResult(BaseModel):
    success: bool
    tool_name: str
    tool_version: str = "1"
    patch: CollectedResearch = Field(default_factory=CollectedResearch)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False


class ResearchTool(Protocol):
    name: str
    version: str
    fulfills: tuple[str, ...]

    async def execute(self, request: ToolRequest) -> ToolResult: ...
