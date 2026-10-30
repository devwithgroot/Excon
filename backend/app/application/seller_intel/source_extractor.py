"""Stage 5: LLM fact extraction, per source, with every claim re-grounded in its source text."""

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.application.seller_intel.document_models import IntelSourceType, Source
from app.application.seller_intel.markdown_normalizer import chunk_markdown
from app.domain.company_intelligence import ClaimCategory
from app.domain.evidence import EvidenceItem, SourceType

logger = logging.getLogger(__name__)

PROMPT_VERSION = "source-extract/v1"

SYSTEM = """You extract facts about the SELLER company "{company}" from the sources below.
Each source starts with a line like === S1 | <name> ===.

Rules:
- Only extract what a source states about {company}. Never invent or guess.
- Do not report facts about {company}'s customers, partners or competitors as {company}'s own.
- Copy "excerpt" verbatim from the source (max 200 characters). It proves the claim.
- "source" is the S-label of the source the excerpt came from.
- support="explicit" when the text states it; "inferred" only when it clearly implies it.
- Return {{"claims": []}} if the sources contain no seller facts.

Categories (pick exactly one per claim):
- description: what the company is / does, in one sentence
- industry: the company's OWN industry (e.g. "B2B SaaS", "IT services")
- business_model: how it makes money (subscription, project fees, licences, ...)
- geography: where it is based or operates
- company_size: headcount or size, only if stated
- product: a packaged software/hardware offering it sells. Put the product name in "name"
- service: work it performs for clients (consulting, implementation, audits, support). Put the service name in "name"
- feature: one capability of a product. Put the product name in "name" if known
- use_case: a concrete situation where its offering is used
- industry_served: an industry it sells to
- customer_segment: a type or size of customer it serves (e.g. "MSMEs", "enterprise retailers")
- value_proposition: why customers buy from it
- problem_solved: a customer problem it addresses
- differentiator: how it claims to differ from alternatives
- limitation: who or what it says it is NOT for
"""


class ExtractedClaim(BaseModel):
    category: ClaimCategory
    value: str = Field(description="The fact in plain words, max 160 characters")
    name: str | None = Field(default=None, description="Product/service name for product, service, feature")
    excerpt: str = Field(description="Verbatim supporting text from the source")
    source: str = Field(description="Source label such as S1")
    support: Literal["explicit", "inferred"] = "explicit"


class SourceExtraction(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class GroundedClaim(BaseModel):
    claim: ExtractedClaim
    source_id: str
    evidence: EvidenceItem


class ExtractionResult(BaseModel):
    claims: list[GroundedClaim] = Field(default_factory=list)
    calls: int = 0
    failed_calls: int = 0
    dropped_ungrounded: int = 0
    source_status: dict[str, str] = Field(default_factory=dict)


Progress = Callable[[str], Awaitable[None]] | None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`#>|]", " ", text)).strip().lower()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{3,}", text.lower())


def excerpt_grounded(excerpt: str, text: str) -> bool:
    excerpt_norm, text_norm = _norm(excerpt), _norm(text)
    if len(excerpt_norm) < 8:
        return False
    if excerpt_norm in text_norm:
        return True
    tokens = _tokens(excerpt_norm)
    if len(tokens) < 3:
        return False
    hits = sum(1 for token in tokens if token in text_norm)
    return hits / len(tokens) >= 0.8


def value_supported(value: str, text: str) -> bool:
    tokens = [token for token in _tokens(value) if len(token) >= 4]
    if not tokens:
        return True
    text_norm = _norm(text)
    return sum(1 for token in tokens if token in text_norm) / len(tokens) >= 0.5


def section_reference(markdown: str, excerpt: str) -> str | None:
    """Nearest page marker and heading above the line where the excerpt starts."""
    lead = _tokens(excerpt)[:4]
    if not lead:
        return None
    page: str | None = None
    heading: str | None = None
    for line in markdown.splitlines():
        page_match = re.match(r"<!-- page (\d+) -->", line.strip())
        if page_match:
            page = page_match.group(1)
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading_match:
            heading = heading_match.group(1).strip()
        line_tokens = set(_tokens(line))
        if all(token in line_tokens for token in lead):
            refs = [f"page {page}"] if page else []
            if heading:
                refs.append(f"section: {heading[:80]}")
            return ", ".join(refs) or None
    return None


def pack_sources(sources: list[Source], chunk_chars: int) -> list[list[tuple[str, Source, str]]]:
    """Group (label, source, text) so small pages share an LLM call and big ones are chunked."""
    packs: list[list[tuple[str, Source, str]]] = []
    current: list[tuple[str, Source, str]] = []
    size = 0
    for source in sources:
        for piece in chunk_markdown(source.normalized_markdown, chunk_chars):
            if current and size + len(piece) > chunk_chars:
                packs.append(current)
                current, size = [], 0
            current.append(("", source, piece))
            size += len(piece) + 80
    if current:
        packs.append(current)
    labelled = []
    for pack in packs:
        labelled.append([(f"S{index}", source, text) for index, (_, source, text) in enumerate(pack, start=1)])
    return labelled


def _prioritize(sources: list[Source]) -> list[Source]:
    from app.application.seller_intel.website_crawler import page_score

    def rank(source: Source) -> tuple[int, int]:
        if source.source_type == IntelSourceType.document:
            return (0, -200)
        return (1, -page_score(source.source_url or ""))

    return sorted(sources, key=rank)


def _evidence_source_type(source: Source) -> SourceType:
    if source.source_type == IntelSourceType.document:
        return SourceType.document
    if source.source_type == IntelSourceType.search_result:
        return SourceType.web_search
    return SourceType.website


async def extract_sources(
    sources: list[Source],
    *,
    company_name: str,
    mlx: Any,
    chunk_chars: int,
    max_calls: int,
    progress: Progress = None,
) -> ExtractionResult:
    result = ExtractionResult()
    packs = pack_sources(_prioritize(sources), chunk_chars)
    if len(packs) > max_calls:
        skipped = {source.source_id for pack in packs[max_calls:] for _, source, _ in pack}
        for source_id in skipped:
            result.source_status.setdefault(source_id, "skipped_budget")
        packs = packs[:max_calls]
    system = SYSTEM.format(company=company_name)
    for index, pack in enumerate(packs, start=1):
        if progress:
            await progress(f"Extracting facts ({index}/{len(packs)})")
        user = "\n\n".join(
            f"=== {label} | {source.source_name} ===\n{text}" for label, source, text in pack
        )
        result.calls += 1
        try:
            extraction = await mlx.complete_model(system, user, SourceExtraction, max_tokens=2500)
        except Exception as exc:
            logger.warning("extraction call %d failed: %s", index, exc)
            extraction = None
        if extraction is None:
            result.failed_calls += 1
            for _, source, _ in pack:
                result.source_status.setdefault(source.source_id, "extraction_failed")
            continue
        for _, source, _ in pack:
            result.source_status[source.source_id] = "extracted"
        result.claims.extend(_ground(extraction.claims, pack, result))
    return result


def _ground(
    claims: list[ExtractedClaim],
    pack: list[tuple[str, Source, str]],
    result: ExtractionResult,
) -> list[GroundedClaim]:
    by_label = {label: (source, text) for label, source, text in pack}
    grounded: list[GroundedClaim] = []
    now = datetime.now(timezone.utc)
    for claim in claims:
        value = re.sub(r"\s+", " ", claim.value).strip()[:300]
        if not value:
            continue
        candidates = [by_label[claim.source]] if claim.source in by_label else []
        candidates += [item for label, item in by_label.items() if label != claim.source]
        match = next(((source, text) for source, text in candidates if excerpt_grounded(claim.excerpt, text)), None)
        if match is None:
            result.dropped_ungrounded += 1
            continue
        source, text = match
        support = claim.support
        if support == "explicit" and not value_supported(f"{claim.name or ''} {value}", text):
            support = "inferred"
        evidence = EvidenceItem(
            field_key=f"seller.{claim.category}",
            extracted_value=value,
            source_id=source.source_id,
            source_title=source.source_name,
            source_url=source.source_url,
            source_type=_evidence_source_type(source),
            retrieved_at=now,
            supporting_excerpt=claim.excerpt.strip()[:400],
            section_reference=section_reference(source.normalized_markdown, claim.excerpt),
            extraction_method=f"llm:{PROMPT_VERSION}",
            confidence=0.8 if support == "explicit" else 0.5,
            support=support,
        )
        grounded.append(
            GroundedClaim(
                claim=claim.model_copy(update={"value": value, "support": support}),
                source_id=source.source_id,
                evidence=evidence,
            )
        )
    return grounded
