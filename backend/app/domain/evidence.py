from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    web_search = "web_search"
    news = "news"
    website = "website"
    document = "document"
    people = "people"


class Freshness(str, Enum):
    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex)
    field_key: str
    extracted_value: str | None = None
    source_url: str | None = None
    source_type: SourceType
    source_published_at: datetime | None = None
    retrieved_at: datetime
    supporting_excerpt: str = ""
    extraction_method: str = "provider"
    confidence: float = Field(default=0.5, ge=0, le=1)
    freshness: Freshness = Freshness.unknown
