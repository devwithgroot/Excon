"""LangChain tool: website_docs.

The LangGraph agent in app.graphs.research calls `website_docs_tool`.
FastAPI does not call this file directly.
"""

import asyncio
import html
import io
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from langchain_core.tools import StructuredTool

from app.config import get_settings
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    ParameterStatus,
)
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.tool_contract import DocumentInput, ToolRequest, ToolResult
from app.infrastructure.tools.http_safety import url_is_public_http
from app.infrastructure.tools.mlx_client import MlxClient, grounded_only
from app.infrastructure.tools.tavily import TavilyClient

SAFE_CONTENT_TYPES = {"text/html", "text/plain", "application/xhtml+xml"}
MAX_REDIRECTS = 3
COMPANY_KEYS = (
    "name",
    "domain",
    "description",
    "industry",
    "headquarters",
    "products",
    "size",
    "founded",
)
INNER_PATHS = (
    "/about",
    "/about-us",
    "/company",
    "/our-story",
    "/locations",
    "/contact",
    "/products",
    "/product",
    "/solutions",
)
FOCUS_PATHS = {
    "headquarters": ("/locations", "/contact", "/about", "/about-us", "/company"),
    "products": ("/products", "/product", "/solutions", "/platform"),
    "size": ("/about", "/about-us", "/company", "/careers"),
    "founded": ("/about", "/about-us", "/company", "/our-story"),
}
LINK_HINTS = (
    "about",
    "company",
    "product",
    "solution",
    "platform",
    "team",
    "leader",
    "career",
    "job",
    "contact",
    "location",
    "office",
    "story",
    "who-we",
    "investor",
    "press",
)
SKIP_LINK_HINTS = (
    "login",
    "signup",
    "privacy",
    "terms",
    "cookie",
    "careers/apply",
    "/guides/",
    "/docs/",
    "/blog/",
    "/use-cases/",
    "/customers/",
    "/listing/",
    "/job/",
)
SITE_QUERIES = {
    "headquarters": 'headquarters OR headquartered OR "based in" OR office',
    "products": "products OR platform OR solutions",
    "size": 'employees OR "team of" OR headcount OR staff',
    "founded": 'founded OR established OR "since 19" OR "since 20"',
}

EXTRACT_SYSTEM = (
    "Extract only facts present in the provided text. "
    "Return JSON with keys name, domain, description, industry, "
    "headquarters, products, size, founded. Use null when the text does not state a fact. "
    "Never invent or guess."
)


class WebsiteDocsTool:
    name = "website_docs"
    version = "1"
    fulfills = tuple(f"company.{key}" for key in COMPANY_KEYS)

    def __init__(
        self,
        mlx: MlxClient | None = None,
        fetch_page=None,
        is_safe_url=None,
        tavily: TavilyClient | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
        max_pages: int | None = None,
    ) -> None:
        settings = get_settings()
        self.mlx = mlx
        self.fetch_page = fetch_page or fetch_public_text
        self.is_safe_url = is_safe_url or url_is_public_http
        self.tavily = tavily if tavily is not None else TavilyClient()
        self.timeout = timeout if timeout is not None else settings.http_timeout_seconds
        self.max_bytes = max_bytes if max_bytes is not None else settings.website_max_bytes
        self.max_pages = max_pages if max_pages is not None else settings.website_max_pages

    async def execute(self, request: ToolRequest) -> ToolResult:
        retrieved_at = datetime.now(timezone.utc)
        sources: list[tuple[str, SourceType, str | None, str]] = []

        page_url = request.website_url or _url_from_domain(request.company_domain)
        root = _root_domain(page_url or request.company_domain)
        homepage_html = ""
        if page_url and await asyncio.to_thread(self.is_safe_url, page_url):
            homepage_html = await self._add_page(sources, page_url)

        if page_url and root:
            for inner in _candidate_urls(page_url, homepage_html, root, focus=request.focus):
                if len([s for s in sources if s[1] == SourceType.website]) >= self.max_pages:
                    break
                if not await asyncio.to_thread(self.is_safe_url, inner):
                    continue
                await self._add_page(sources, inner)

        extracted = _fields_from_sources(request, sources)
        missing = [key for key in SITE_QUERIES if not extracted.get(key)]
        if request.focus and request.focus in SITE_QUERIES:
            missing = [request.focus]
        if missing and root:
            await self._fill_from_site_search(request, sources, root, missing)

        for document in request.documents:
            text = document_text(document)
            if text:
                sources.append((text, SourceType.document, None, document.filename))

        if not sources:
            empty = {key: FieldValue(status=ParameterStatus.not_found_this_run) for key in COMPANY_KEYS}
            return ToolResult(
                success=True,
                tool_name=self.name,
                patch=CollectedResearch(company=CompanyBlock(**empty)),
            )

        extracted = _fields_from_sources(request, sources)
        combined = _combined_text(sources)
        extracted = await self._extract_fields(request, combined, extracted)
        evidence: list[EvidenceItem] = []
        fields: dict[str, FieldValue] = {}

        for key in COMPANY_KEYS:
            value = extracted.get(key)
            source_text, source_type, source_url, _label = _best_source(key, value, sources, request)
            if value:
                item = EvidenceItem(
                    field_key=f"company.{key}",
                    extracted_value=value,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    supporting_excerpt=source_text[:400],
                    extraction_method="grounded" if self.mlx else "heuristic",
                    confidence=0.7 if source_type == SourceType.website else 0.6,
                )
                evidence.append(item)
                fields[key] = FieldValue(
                    value=value,
                    status=ParameterStatus.supported,
                    evidence_ids=[item.evidence_id],
                )
            else:
                fields[key] = FieldValue(status=ParameterStatus.not_found_this_run)

        return ToolResult(
            success=True,
            tool_name=self.name,
            patch=CollectedResearch(company=CompanyBlock(**fields), evidence=evidence),
            evidence=evidence,
        )

    async def _add_page(
        self,
        sources: list[tuple[str, SourceType, str | None, str]],
        url: str,
    ) -> str:
        if any(item[2] == url for item in sources):
            return ""
        try:
            raw = await self.fetch_page(
                url,
                timeout=self.timeout,
                max_bytes=self.max_bytes,
            )
        except Exception:
            return ""
        text = html_to_text(raw)
        if text:
            sources.append((text, SourceType.website, url, url))
        return raw

    async def _fill_from_site_search(
        self,
        request: ToolRequest,
        sources: list[tuple[str, SourceType, str | None, str]],
        root: str,
        missing: list[str],
    ) -> None:
        already = {item[2] for item in sources if item[2]}
        extra = 0
        for field in missing:
            if extra >= 3:
                return
            query = f"site:{root} {request.company_name} {SITE_QUERIES[field]}"
            try:
                hits = await self.tavily.search(query, max_results=3, days=None)
            except Exception:
                continue
            for hit in hits:
                if extra >= 3:
                    return
                if not hit.url or hit.url in already:
                    continue
                if not _same_site(hit.url, root) or not await asyncio.to_thread(
                    self.is_safe_url, hit.url
                ):
                    continue
                if _skip_path(hit.url):
                    continue
                if not any(hint in (urlparse(hit.url).path or "").lower() for hint in LINK_HINTS):
                    continue
                raw = await self._add_page(sources, hit.url)
                if raw:
                    already.add(hit.url)
                    extra += 1

    async def _extract_fields(
        self,
        request: ToolRequest,
        text: str,
        found: dict[str, str | None],
    ) -> dict[str, str | None]:
        if not self.mlx:
            return found
        try:
            payload = await self.mlx.complete_json(
                EXTRACT_SYSTEM,
                f"Company: {request.company_name}\n\nText:\n{text[:8000]}",
            )
        except Exception:
            return found
        if not isinstance(payload, dict):
            return found
        for key in COMPANY_KEYS:
            grounded = grounded_only(_as_str(payload.get(key)), text)
            if grounded and not found.get(key):
                found[key] = grounded
        return found


def _fields_from_sources(
    request: ToolRequest,
    sources: list[tuple[str, SourceType, str | None, str]],
) -> dict[str, str | None]:
    merged: dict[str, str | None] = {key: None for key in COMPANY_KEYS}
    ranked = sorted(sources, key=lambda item: _source_rank(item[2]))
    for text, _source_type, _url, _label in ranked:
        found = heuristic_company_fields(request, text)
        for key in COMPANY_KEYS:
            if found.get(key) and not merged.get(key):
                merged[key] = found[key]
    return merged


def _source_rank(url: str | None) -> int:
    if not url:
        return 1
    path = (urlparse(url).path or "/").lower()
    if _skip_path(url):
        return 50
    for index, hint in enumerate(("about", "company", "location", "contact", "product", "story")):
        if hint in path:
            return index
    return 20


def _skip_path(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(skip in path for skip in SKIP_LINK_HINTS)


def _combined_text(sources: list[tuple[str, SourceType, str | None, str]]) -> str:
    return "\n\n".join(text for text, _, _, _ in sources)


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _url_from_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    host = domain.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if not host:
        return None
    return f"https://{host}"


def _root_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    if not host:
        return None
    return host.lower().removeprefix("www.")


def _same_site(url: str, root: str) -> bool:
    host = _root_domain(url)
    return bool(host and (host == root or host.endswith("." + root)))


def _candidate_urls(
    base_url: str,
    homepage_html: str,
    root: str,
    focus: str | None = None,
) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    found: list[str] = []
    seen = {base_url.rstrip("/")}
    paths = list(FOCUS_PATHS.get(focus or "", ())) + [path for path in INNER_PATHS]
    for path in paths:
        url = urljoin(origin + "/", path.lstrip("/"))
        if url.rstrip("/") not in seen:
            seen.add(url.rstrip("/"))
            found.append(url)
    for href in re.findall(r"""href=["']([^"'#]+)""", homepage_html, flags=re.I):
        absolute = urljoin(base_url, href)
        if not _same_site(absolute, root):
            continue
        path = (urlparse(absolute).path or "/").lower()
        if _skip_path(absolute):
            continue
        if not any(hint in path for hint in LINK_HINTS):
            continue
        normalized = absolute.split("#")[0]
        if normalized.rstrip("/") in seen:
            continue
        seen.add(normalized.rstrip("/"))
        found.append(normalized)
    return found


def _best_source(
    key: str,
    value: str | None,
    sources: list[tuple[str, SourceType, str | None, str]],
    request: ToolRequest,
) -> tuple[str, SourceType, str | None, str]:
    if value:
        needle = value.lower()
        for text, source_type, source_url, label in sources:
            if needle in text.lower():
                return text, source_type, source_url, label
    if sources:
        return sources[0]
    return "", SourceType.website, request.website_url, request.company_name


def html_to_text(raw: str) -> str:
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def document_text(document: DocumentInput) -> str:
    if document.text and document.text.strip():
        return document.text.strip()
    if document.raw_bytes and document.filename.lower().endswith(".pdf"):
        return extract_pdf_text(document.raw_bytes)
    if document.raw_bytes:
        return document.raw_bytes.decode("utf-8", errors="replace").strip()
    return ""


def extract_pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    pages = [page.extract_text() or "" for page in reader.pages]
    return re.sub(r"\s+", " ", " ".join(pages)).strip()


async def fetch_public_text(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    allowed_types: set[str] | frozenset[str] = frozenset(SAFE_CONTENT_TYPES),
) -> str:
    if not await asyncio.to_thread(url_is_public_http, url):
        raise ValueError("blocked_url")
    current = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not await asyncio.to_thread(url_is_public_http, current):
                raise ValueError("blocked_url")
            response = await client.get(
                current,
                headers={"User-Agent": "ExconResearch/0.1"},
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("bad_redirect")
                current = str(response.url.join(location))
                continue
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type not in allowed_types:
                raise ValueError("unsupported_type")
            body = response.content[: max_bytes + 1]
            if len(body) > max_bytes:
                body = body[:max_bytes]
            return body.decode(response.encoding or "utf-8", errors="replace")
    raise ValueError("too_many_redirects")


def heuristic_company_fields(request: ToolRequest, text: str) -> dict[str, str | None]:
    found: dict[str, str | None] = {key: None for key in COMPANY_KEYS}
    if request.company_name and request.company_name.lower() in text.lower():
        found["name"] = request.company_name
    domain = request.company_domain or _host_from_url(request.website_url)
    if domain:
        found["domain"] = domain.lower().removeprefix("www.")
    meta = _first_match(
        r"\b(?:industry|sector)\s*:\s*([A-Za-z][A-Za-z &/+-]{2,40})",
        text,
    )
    if meta:
        found["industry"] = meta
    hq = _first_match(
        r"(?:headquartered|headquarters|based) in ([A-Z][A-Za-z]+(?:[\s,]+[A-Z][A-Za-z]+){0,3})",
        text,
    )
    if hq:
        found["headquarters"] = hq.rstrip(" ,.")
    size = _first_match(r"(\d[\d,]{0,6}\+?\s+employees)", text)
    if size:
        found["size"] = size
    products = _first_match(
        r"(?:products?(?: include| we (?:offer|sell)|[:]))\s+([^.]+)",
        text,
    )
    if products:
        found["products"] = products.strip()
    founded = _first_match(
        r"(?:founded|established|since)\s+(?:in\s+)?((?:19|20)\d{2})",
        text,
    )
    if founded:
        found["founded"] = founded
    description = _description_from_text(request.company_name, text)
    if description:
        found["description"] = description
    return found


def _description_from_text(company_name: str, text: str) -> str | None:
    nav = ("sign in", "see all products", "developers resources", "pricing")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(token in lowered for token in nav):
            continue
        if company_name.lower() in lowered and 40 < len(sentence) < 280:
            return sentence.strip()[:400]
    return None


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    return match.group(1).strip()


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).hostname


def as_langchain_tool(instance: "WebsiteDocsTool | None" = None) -> StructuredTool:
    from app.tools.lc_tool import as_research_tool

    return as_research_tool(
        name="website_docs",
        description=(
            "Read the company's official website (homepage and inner pages) and "
            "extract name, domain, description, industry, headquarters, products, "
            "size, founded. Does not invent missing fields."
        ),
        worker=instance or WebsiteDocsTool(),
    )


website_docs_tool = as_langchain_tool
