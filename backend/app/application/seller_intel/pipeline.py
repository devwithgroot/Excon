"""Background seller extraction: documents + website -> sources -> facts -> intelligence -> draft profile."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.application.seller_intel.company_analyzer import analyze_company
from app.application.seller_intel.document_models import ParsedDocument, ParseStatus
from app.application.seller_intel.document_parser import parse_document
from app.application.seller_intel.evidence_consolidator import consolidate
from app.application.seller_intel.icp_generator import generate_icp
from app.application.seller_intel.profile_builder import build_profile, minimal_profile
from app.application.seller_intel.profile_validator import completeness, validate_profile
from app.application.seller_intel.source_extractor import extract_sources
from app.application.seller_intel.source_registry import SourceRegistry
from app.application.seller_intel.website_crawler import crawl_site
from app.config import get_settings
from app.domain.seller_profile import ExtractionMetadata, SellerProfile, SourceSummary
from app.infrastructure.repositories.research import ResearchStore
from app.infrastructure.repositories.seller_intel import SellerIntelStore
from app.infrastructure.uploads import read_upload

logger = logging.getLogger(__name__)

STAGES = [
    "uploading_documents",
    "parsing_documents",
    "crawling_website",
    "normalizing_sources",
    "extracting_facts",
    "consolidating_evidence",
    "analyzing_company",
    "generating_icp",
    "building_profile",
    "validating_profile",
    "ready_for_review",
]

STAGE_LABELS = {
    "uploading_documents": "Uploading documents",
    "parsing_documents": "Parsing documents",
    "crawling_website": "Crawling website",
    "normalizing_sources": "Normalizing sources",
    "extracting_facts": "Extracting facts",
    "consolidating_evidence": "Consolidating evidence",
    "analyzing_company": "Analyzing company",
    "generating_icp": "Generating ICP",
    "building_profile": "Building profile",
    "validating_profile": "Validating profile",
    "ready_for_review": "Ready for review",
}


class JobAborted(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_llm() -> Any:
    from app.infrastructure.tools.mlx_client import MlxClient

    return MlxClient()


def default_search() -> Any:
    settings = get_settings()
    if not settings.tavily_api_key:
        return None
    from app.infrastructure.tools.tavily import TavilyClient

    return TavilyClient()


class _Db:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def run(self, work: Callable[[SellerIntelStore, ResearchStore], Any]) -> Any:
        def call() -> Any:
            session = self.session_factory()
            try:
                result = work(SellerIntelStore(session), ResearchStore(session))
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return await asyncio.to_thread(call)


async def run_extraction_job(
    job_id: str,
    *,
    session_factory: Callable[[], Any],
    mlx: Any = None,
    search: Any = None,
    crawl: Callable[..., Any] | None = None,
) -> None:
    """Never raises: every outcome ends as a succeeded, partial or failed job with a saved draft."""
    db = _Db(session_factory)
    context = await db.run(lambda intel, research: _load(intel, research, job_id))
    if context is None:
        logger.warning("extraction job %s not found", job_id)
        return

    async def stage(name: str, detail: str | None = None) -> None:
        await db.run(lambda intel, _: intel.set_stage(job_id, stage=name, index=STAGES.index(name), detail=detail))

    warnings: list[str] = []
    registry = SourceRegistry()
    try:
        profile = await _pipeline(
            context,
            db=db,
            stage=stage,
            registry=registry,
            warnings=warnings,
            mlx=mlx,
            search=search,
            crawl=crawl or crawl_site,
        )
    except JobAborted as exc:
        await _fail(db, context, registry, warnings, code=exc.code, message=str(exc))
        return
    except Exception as exc:
        logger.exception("extraction job %s crashed", job_id)
        await _fail(db, context, registry, warnings, code="internal_error", message=f"{type(exc).__name__}: {exc}"[:500])
        return

    status = "succeeded" if profile.extraction_metadata.status == "complete" else "partial"
    summary = _summary(profile, registry)

    def finish(intel: SellerIntelStore, research: ResearchStore) -> None:
        seller = research.get_seller(context["seller_id"])
        research.save_seller_draft(seller, profile)
        intel.finish_job(job_id, status=status, warnings=profile.extraction_metadata.warnings, summary=summary)

    await db.run(finish)


def _load(intel: SellerIntelStore, research: ResearchStore, job_id: str) -> dict | None:
    job = intel.get_job(job_id)
    if job is None:
        return None
    seller = research.get_seller(job.seller_id)
    if seller is None:
        return None
    return {
        "job_id": job_id,
        "seller_id": seller.id,
        "company_name": seller.company_name,
        "name": seller.name,
        "website_url": seller.website_url,
        "documents": [
            {
                "id": row.id,
                "filename": row.filename,
                "format": row.original_format,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "storage_path": row.storage_path,
                "parse_status": row.parse_status,
                "parse_error": row.parse_error,
            }
            for row in intel.documents_for_job(job_id)
        ],
    }


async def _pipeline(
    context: dict,
    *,
    db: _Db,
    stage: Callable[..., Any],
    registry: SourceRegistry,
    warnings: list[str],
    mlx: Any,
    search: Any,
    crawl: Callable[..., Any],
) -> SellerProfile:
    settings = get_settings()
    job_id, seller_id = context["job_id"], context["seller_id"]
    company_name = context["company_name"]

    await stage("parsing_documents", f"{len(context['documents'])} document(s)")
    for document in context["documents"]:
        parsed = await asyncio.to_thread(_parse_stored, document)
        await db.run(lambda intel, _, parsed=parsed: intel.record_parse(parsed))
        registry.add_document(parsed)
        if not parsed.usable:
            warnings.append(f"document_{parsed.status.value}: {parsed.filename}: {parsed.error or 'no text'}")

    website = context["website_url"]
    if website:
        await stage("crawling_website", website)
        pages, report = await crawl(website, company_name=company_name, search=search)
        for page in pages:
            registry.add(page)
        if not pages:
            warnings.append(f"website_unreachable: {'; '.join(report.errors[:2]) or website}")
        elif report.errors:
            warnings.append(f"website_partial: {len(report.errors)} page(s) could not be fetched")

    await stage("normalizing_sources", f"{len(registry.usable())} usable source(s)")
    usable = registry.usable()
    if not usable:
        raise JobAborted(
            "no_usable_sources",
            "No readable content: the website could not be fetched and no uploaded document produced text.",
        )
    await db.run(lambda intel, _: intel.save_sources(job_id=job_id, seller_id=seller_id, sources=registry.all()))

    if mlx is None:
        raise JobAborted("llm_unavailable", "The language model is not configured, so the profile cannot be generated.")

    await stage("extracting_facts")
    extraction = await extract_sources(
        usable,
        company_name=company_name,
        mlx=mlx,
        chunk_chars=settings.llm_chunk_chars,
        max_calls=settings.llm_max_extract_calls,
        progress=lambda detail: stage("extracting_facts", detail),
    )
    for source_id, status in extraction.source_status.items():
        registry.mark(source_id, status)
    if extraction.calls and extraction.failed_calls == extraction.calls:
        raise JobAborted("llm_unavailable", "The language model did not return usable output for any source.")
    if extraction.failed_calls:
        warnings.append(f"extraction_partial: {extraction.failed_calls} of {extraction.calls} LLM calls failed")
    if any(status == "skipped_budget" for status in extraction.source_status.values()):
        warnings.append("extraction_budget: some sources were not read because of the LLM call budget")
    if extraction.dropped_ungrounded:
        warnings.append(f"ungrounded_claims_dropped: {extraction.dropped_ungrounded}")
    await db.run(lambda intel, _: intel.save_sources(job_id=job_id, seller_id=seller_id, sources=registry.all()))

    await stage("consolidating_evidence", f"{len(extraction.claims)} grounded claim(s)")
    consolidation = consolidate(extraction.claims)

    await stage("analyzing_company", f"{len(consolidation.facts)} fact(s)")
    intelligence, analysis_warnings = await analyze_company(
        consolidation, company_name=company_name, website_url=website, mlx=mlx
    )
    warnings.extend(analysis_warnings)

    await stage("generating_icp")
    icp, suggestions, icp_warnings = await generate_icp(intelligence, mlx=mlx)
    warnings.extend(icp_warnings)
    intelligence.icp = icp
    intelligence.prospect_suggestions = suggestions
    await db.run(lambda intel, _: intel.save_intelligence(job_id=job_id, seller_id=seller_id, intelligence=intelligence))
    await db.run(lambda intel, _: intel.save_suggestions(job_id=job_id, seller_id=seller_id, suggestions=suggestions))

    await stage("building_profile")
    profile = build_profile(
        intelligence,
        contact_name=context["name"],
        seller_id=seller_id,
        sources=registry.all(),
        job_id=job_id,
        warnings=warnings,
    )

    await stage("validating_profile")
    profile = await validate_profile(profile, mlx=mlx)
    if any(warning.startswith(("website_unreachable", "extraction_partial", "analysis_llm_failed")) for warning in warnings):
        profile.extraction_metadata.status = "partial"
    return profile


def _parse_stored(document: dict) -> ParsedDocument:
    base = {
        "document_id": document["id"],
        "filename": document["filename"],
        "original_format": document["format"],
        "mime_type": document["mime_type"],
        "size_bytes": document["size_bytes"],
        "storage_path": document["storage_path"],
    }
    if document["parse_status"] in {ParseStatus.unsupported_format.value, ParseStatus.failed.value}:
        return ParsedDocument(**base, status=ParseStatus(document["parse_status"]), error=document["parse_error"])
    try:
        data = read_upload(document["storage_path"])
    except Exception as exc:
        return ParsedDocument(**base, status=ParseStatus.failed, error=f"stored file unreadable: {exc}"[:300])
    return parse_document(
        document["filename"],
        data,
        mime_type=document["mime_type"],
        storage_path=document["storage_path"],
        document_id=document["id"],
    )


async def _fail(db: _Db, context: dict, registry: SourceRegistry, warnings: list[str], *, code: str, message: str) -> None:
    """Keep the identity draft so the user can fill the profile in by hand."""
    profile = minimal_profile(context, seller_id=context["seller_id"])
    profile.extraction_metadata = ExtractionMetadata(
        job_id=context["job_id"],
        status="failed",
        sources=[
            SourceSummary(
                source_id=source.source_id,
                source_type=source.source_type.value,
                name=source.source_name,
                url=source.source_url,
                status=source.extraction_status,
                error=source.error,
            )
            for source in registry.all()
        ],
        warnings=[f"{code}: {message}", *warnings],
    )
    profile.extraction_metadata.completeness = completeness(profile)

    def finish(intel: SellerIntelStore, research: ResearchStore) -> None:
        seller = research.get_seller(context["seller_id"])
        if seller is not None:
            research.save_seller_draft(seller, profile)
        intel.finish_job(context["job_id"], status="failed", error=f"{code}: {message}", warnings=warnings)

    await db.run(finish)


def _summary(profile: SellerProfile, registry: SourceRegistry) -> dict:
    metadata = profile.extraction_metadata
    return {
        "sources": len(registry),
        "usable_sources": len(registry.usable()),
        "products": len(profile.products),
        "services": len(profile.services),
        "evidence": len(profile.evidence),
        "suggestions": len(profile.suggested_prospect_characteristics),
        "missing": list(metadata.missing),
        "conflicts": len(metadata.conflicts),
        "completeness": metadata.completeness,
    }
