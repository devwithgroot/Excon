"""Stage 7: deterministic merge of per-source claims. Conflicts are surfaced, never resolved silently."""

import re

from pydantic import BaseModel, Field

from app.application.seller_intel.source_extractor import GroundedClaim
from app.domain.company_intelligence import (
    REQUIRED_CATEGORIES,
    SINGLE_VALUE_CATEGORIES,
    Conflict,
    ConflictValue,
    ConsolidatedFact,
)
from app.domain.evidence import EvidenceItem

NAMED_CATEGORIES = ("product", "service")
SMALL_SEGMENT = ("small", "smb", "sme", "msme", "startup", "start-up", "micro")
LARGE_SEGMENT = ("enterprise", "large", "fortune", "multinational", "global 2000")
STOP = {"the", "and", "for", "with", "our", "their", "that", "this", "from", "into", "your", "are", "you"}


class Consolidation(BaseModel):
    facts: list[ConsolidatedFact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    def by_category(self, category: str) -> list[ConsolidatedFact]:
        return [fact for fact in self.facts if fact.category == category]


def _key_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in STOP}


def similar(a: str, b: str) -> bool:
    left, right = _key_tokens(a), _key_tokens(b)
    if not left or not right:
        return a.strip().lower() == b.strip().lower()
    overlap, union = len(left & right), len(left | right)
    smaller = min(len(left), len(right))
    if overlap == smaller and (smaller >= 2 or union <= 3):
        return True
    return overlap / union >= 0.6


class _Group:
    def __init__(self, claim: GroundedClaim) -> None:
        self.category = claim.claim.category
        self.name = (claim.claim.name or "").strip() or None
        self.members = [claim]

    @property
    def label(self) -> str:
        if self.category in NAMED_CATEGORIES and self.name:
            return self.name
        return self.representative.claim.value

    @property
    def representative(self) -> GroundedClaim:
        explicit = [member for member in self.members if member.claim.support == "explicit"] or self.members
        return max(explicit, key=lambda member: len(member.claim.value))

    def matches(self, claim: GroundedClaim) -> bool:
        if claim.claim.category != self.category:
            return False
        if self.category in NAMED_CATEGORIES:
            other = (claim.claim.name or claim.claim.value).strip()
            return similar(self.name or self.representative.claim.value, other)
        return similar(self.representative.claim.value, claim.claim.value)


def consolidate(claims: list[GroundedClaim]) -> Consolidation:
    groups: list[_Group] = []
    for claim in claims:
        target = next((group for group in groups if group.matches(claim)), None)
        if target is None:
            groups.append(_Group(claim))
        else:
            target.members.append(claim)
            if not target.name and claim.claim.name:
                target.name = claim.claim.name.strip()

    facts: list[ConsolidatedFact] = []
    for index, group in enumerate(groups, start=1):
        source_ids = sorted({member.source_id for member in group.members})
        explicit = any(member.claim.support == "explicit" for member in group.members)
        base = 0.7 if explicit else 0.45
        value = group.representative.claim.value
        variants = list(dict.fromkeys(m.claim.value for m in group.members if m.claim.value != value))
        facts.append(
            ConsolidatedFact(
                fact_id=f"F{index}",
                category=group.category,
                value=value,
                name=group.name,
                variants=variants[:5],
                evidence_ids=[member.evidence.evidence_id for member in group.members],
                source_ids=source_ids,
                support="explicit" if explicit else "inferred",
                confidence=round(min(0.95, base + 0.1 * (len(source_ids) - 1)), 2),
            )
        )

    return Consolidation(
        facts=facts,
        conflicts=_conflicts(facts),
        missing=_missing(facts),
        evidence=[claim.evidence for claim in claims],
    )


def _conflicts(facts: list[ConsolidatedFact]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for category in SINGLE_VALUE_CATEGORIES:
        values = [fact for fact in facts if fact.category == category]
        if len(values) > 1 and len({tuple(fact.source_ids) for fact in values}) > 1:
            conflicts.append(
                Conflict(
                    field=category,
                    values=[_conflict_value(fact) for fact in values],
                    note="Sources state different values; pick one or keep both.",
                )
            )
    segments = [fact for fact in facts if fact.category == "customer_segment"]
    small = [fact for fact in segments if _mentions(fact.value, SMALL_SEGMENT)]
    large = [fact for fact in segments if _mentions(fact.value, LARGE_SEGMENT)]
    if small and large and set(sum((f.source_ids for f in small), [])) != set(sum((f.source_ids for f in large), [])):
        conflicts.append(
            Conflict(
                field="customer_segment",
                values=[_conflict_value(fact) for fact in small + large],
                note="Sources disagree on customer size (small businesses vs enterprise).",
            )
        )
    return conflicts


def _mentions(value: str, words: tuple[str, ...]) -> bool:
    lowered = f" {value.lower()} "
    return any(re.search(rf"\b{re.escape(word)}", lowered) for word in words)


def _conflict_value(fact: ConsolidatedFact) -> ConflictValue:
    return ConflictValue(value=fact.value, evidence_ids=fact.evidence_ids, source_ids=fact.source_ids)


def _missing(facts: list[ConsolidatedFact]) -> list[str]:
    present = {fact.category for fact in facts}
    missing: list[str] = []
    for category in REQUIRED_CATEGORIES:
        if category == "product_or_service":
            if not present & {"product", "service"}:
                missing.append(category)
        elif category not in present:
            missing.append(category)
    return missing
