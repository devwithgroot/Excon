from enum import Enum

from pydantic import BaseModel, Field

from app.domain.evidence import EvidenceItem


class ParameterStatus(str, Enum):
    unknown = "unknown"
    supported = "supported"
    not_found_this_run = "not_found_this_run"


class FieldValue(BaseModel):
    value: str | None = None
    status: ParameterStatus = ParameterStatus.unknown
    evidence_ids: list[str] = Field(default_factory=list)


class CompanyBlock(BaseModel):
    name: FieldValue = Field(default_factory=FieldValue)
    domain: FieldValue = Field(default_factory=FieldValue)
    description: FieldValue = Field(default_factory=FieldValue)
    industry: FieldValue = Field(default_factory=FieldValue)
    headquarters: FieldValue = Field(default_factory=FieldValue)
    products: FieldValue = Field(default_factory=FieldValue)
    size: FieldValue = Field(default_factory=FieldValue)
    founded: FieldValue = Field(default_factory=FieldValue)


class SignalsBlock(BaseModel):
    funding: FieldValue = Field(default_factory=FieldValue)
    hiring: FieldValue = Field(default_factory=FieldValue)
    tech_shift: FieldValue = Field(default_factory=FieldValue)
    acquisition: FieldValue = Field(default_factory=FieldValue)
    new_product: FieldValue = Field(default_factory=FieldValue)
    expansion: FieldValue = Field(default_factory=FieldValue)


class NewsItem(BaseModel):
    title: str
    url: str
    published_at: str | None = None
    excerpt: str = ""
    evidence_id: str


class PersonRecord(BaseModel):
    name: str
    title: str | None = None
    role_description: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    evidence_id: str


class CollectedResearch(BaseModel):
    company: CompanyBlock = Field(default_factory=CompanyBlock)
    signals: SignalsBlock = Field(default_factory=SignalsBlock)
    news: list[NewsItem] = Field(default_factory=list)
    people: list[PersonRecord] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    def missing_parameters(self) -> list[str]:
        missing: list[str] = []
        for name, field in self.company:
            if field.status != ParameterStatus.supported:
                missing.append(f"company.{name}")
        for name, field in self.signals:
            if field.status != ParameterStatus.supported:
                missing.append(f"signals.{name}")
        if not self.news:
            missing.append("news")
        if not self.people:
            missing.append("people")
        return missing
