from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ParseStatus(str, Enum):
    parsed = "parsed"
    empty = "empty"
    failed = "failed"
    unsupported_format = "unsupported_format"


class IntelSourceType(str, Enum):
    website_page = "website_page"
    document = "document"
    search_result = "search_result"


class ParsedDocument(BaseModel):
    document_id: str = Field(default_factory=lambda: uuid4().hex)
    filename: str
    original_format: str
    mime_type: str | None = None
    size_bytes: int = 0
    storage_path: str | None = None
    markdown: str = ""
    status: ParseStatus
    error: str | None = None
    sections: list[str] = Field(default_factory=list)
    page_count: int | None = None
    parsed_at: datetime = Field(default_factory=_now)

    @property
    def usable(self) -> bool:
        return self.status == ParseStatus.parsed and bool(self.markdown.strip())


class Source(BaseModel):
    """One identifiable input to the intelligence pipeline: a page, a document, a search hit."""

    source_id: str = Field(default_factory=lambda: f"src_{uuid4().hex[:12]}")
    source_type: IntelSourceType
    source_name: str
    source_url: str | None = None
    original_content_reference: str | None = None
    normalized_markdown: str = ""
    extraction_status: str = "pending"
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)


class CrawlReport(BaseModel):
    root_url: str
    pages_fetched: int = 0
    used_sitemap: bool = False
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
