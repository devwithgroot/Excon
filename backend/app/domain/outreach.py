from typing import Literal

from pydantic import BaseModel, Field


class OutreachDraft(BaseModel):
    draft_id: str
    run_id: str
    seller_id: str | None = None
    person_evidence_id: str
    person_name: str
    person_title: str | None = None
    person_linkedin_url: str | None = None
    offering: str | None = None
    offering_reason: str | None = None
    relevance: str = ""
    cited_facts: list[str] = Field(default_factory=list)
    linkedin_connect: str = ""
    linkedin_message: str = ""
    whatsapp: str = ""
    status: Literal["draft", "approved", "rejected"] = "draft"
    version: int = 1
    skipped_reason: str | None = None


class OutreachBatch(BaseModel):
    run_id: str
    status: str
    drafts: list[OutreachDraft] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)
    error: str | None = None
