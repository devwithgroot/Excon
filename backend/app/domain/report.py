from typing import Literal

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class LeadScores(BaseModel):
    completeness: ScoreBreakdown
    evidence_quality: ScoreBreakdown
    qualification: ScoreBreakdown
    fit: ScoreBreakdown
    contact_relevance: ScoreBreakdown
    overall: int = Field(ge=0, le=100)
    recommendation: Literal["pursue", "consider", "deprioritize"]
    recommendation_reason: str


class ProductMatch(BaseModel):
    offering: str
    reason: str
    matched_lead_signals: list[str] = Field(default_factory=list)


class LeadReportBody(BaseModel):
    report_id: str
    run_id: str
    seller_id: str | None = None
    seller_version: int = 0
    scores: LeadScores
    overview: str
    why_fit: list[str] = Field(default_factory=list)
    why_not: list[str] = Field(default_factory=list)
    product_matches: list[ProductMatch] = Field(default_factory=list)
    recommended_action: str
    conversation_angle: str
    people_summary: str = ""
    gaps: list[str] = Field(default_factory=list)
