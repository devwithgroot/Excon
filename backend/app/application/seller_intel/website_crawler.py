"""Same-domain crawl of a seller's site: sitemap + link discovery, prioritized by page type."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.application.seller_intel.document_models import CrawlReport, IntelSourceType, Source
from app.application.seller_intel.markdown_normalizer import html_to_markdown, page_title
from app.application.seller_intel.source_registry import content_fingerprint
from app.config import get_settings
from app.infrastructure.tools.http_safety import url_is_public_http
from app.infrastructure.tools.website_docs import fetch_public_text

logger = logging.getLogger(__name__)

FetchPage = Callable[..., Awaitable[str]]

XML_TYPES = frozenset({"application/xml", "text/xml", "application/rss+xml"})
SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")
MAX_CHILD_SITEMAPS = 3
MIN_PAGE_CHARS = 80

PRIORITY = (
    ("about", 10),
    ("product", 10),
    ("service", 10),
    ("solution", 10),
    ("what-we", 9),
    ("who-we", 8),
    ("company", 8),
    ("platform", 8),
    ("feature", 8),
    ("industr", 8),
    ("use-case", 7),
    ("usecase", 7),
    ("how-it", 6),
    ("pricing", 6),
    ("customer", 6),
    ("case-stud", 6),
    ("testimonial", 5),
    ("integration", 5),
    ("partner", 5),
    ("team", 4),
    ("contact", 4),
    ("career", 3),
)
SKIP_PARTS = (
    "login", "log-in", "signin", "sign-in", "signup", "sign-up", "register", "privacy", "terms",
    "cookie", "legal", "gdpr", "cart", "checkout", "account", "wp-admin", "wp-json", "/feed",
    "/tag/", "/category/", "/author/", "/page/", "unsubscribe",
)
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mp3",
    ".css", ".js", ".xml", ".ico", ".woff", ".woff2", ".json", ".txt",
)
LOW_VALUE = ("blog", "news", "press", "article", "post", "event", "webinar")


class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 5, days: int | None = 90): ...


def root_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", "", ""))


def same_site(url: str, root: str) -> bool:
    host = root_host(url)
    return bool(host) and (host == root or host.endswith("." + root))


def should_skip(url: str) -> bool:
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return True
    path = urlparse(lowered).path
    return path.endswith(SKIP_EXTENSIONS) or any(part in lowered for part in SKIP_PARTS)


def page_score(url: str) -> int:
    path = (urlparse(url).path or "/").lower()
    if path in {"", "/"}:
        return 100
    segments = [segment for segment in path.split("/") if segment]
    if any(word in path for word in LOW_VALUE):
        return 1 if len(segments) == 1 else 0
    best = max((points for hint, points in PRIORITY if hint in path), default=2)
    return max(best - (len(segments) - 1), 1)


def links_from_html(html: str, base_url: str, root: str) -> list[str]:
    found: list[str] = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if same_site(absolute, root) and not should_skip(absolute):
            found.append(normalize_url(absolute))
    return found


def urls_from_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Return (page URLs, child sitemap URLs)."""
    locs = [loc.strip() for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml, flags=re.I)]
    if re.search(r"<sitemapindex", xml, flags=re.I):
        return [], locs
    return locs, []


async def _default_sitemap_fetch(url: str, *, timeout: float, max_bytes: int) -> str:
    return await fetch_public_text(url, timeout=timeout, max_bytes=max_bytes, allowed_types=XML_TYPES)


async def crawl_site(
    website_url: str,
    *,
    company_name: str = "",
    fetch_page: FetchPage | None = None,
    fetch_sitemap: FetchPage | None = None,
    is_safe_url: Callable[[str], bool] | None = None,
    search: SearchClient | None = None,
    max_pages: int | None = None,
    max_depth: int | None = None,
    concurrency: int | None = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
) -> tuple[list[Source], CrawlReport]:
    settings = get_settings()
    fetch = fetch_page or fetch_public_text
    fetch_xml = fetch_sitemap or (_default_sitemap_fetch if fetch_page is None else None)
    safe = is_safe_url or url_is_public_http
    max_pages = max_pages or settings.crawl_max_pages
    max_depth = max_depth if max_depth is not None else settings.crawl_max_depth
    timeout = timeout or settings.crawl_timeout_seconds
    max_bytes = max_bytes or settings.crawl_max_bytes
    parallel = max(concurrency or settings.crawl_concurrency, 1)
    semaphore = asyncio.Semaphore(parallel)

    start = normalize_url(website_url)
    root = root_host(start)
    report = CrawlReport(root_url=start)
    sources: list[Source] = []
    visited: set[str] = set()
    fingerprints: set[str] = set()
    frontier: dict[str, int] = {}

    async def fetch_one(url: str) -> tuple[str, str | None, str | None]:
        async with semaphore:
            try:
                if not await asyncio.to_thread(safe, url):
                    return url, None, "blocked_url"
                return url, await fetch(url, timeout=timeout, max_bytes=max_bytes), None
            except Exception as exc:
                return url, None, f"{type(exc).__name__}: {exc}"[:200]

    def enqueue(url: str, depth: int) -> None:
        url = normalize_url(url)
        if url in visited or depth > max_depth or should_skip(url) or not same_site(url, root):
            return
        if page_score(url) <= 0:
            report.skipped.append(f"{url} (low value)")
            return
        frontier[url] = min(depth, frontier.get(url, depth))

    def accept(url: str, html: str, depth: int) -> None:
        markdown = html_to_markdown(html)
        if len(markdown) < MIN_PAGE_CHARS:
            report.skipped.append(f"{url} (too little text)")
            return
        fingerprint = content_fingerprint(markdown)
        if fingerprint in fingerprints:
            report.skipped.append(f"{url} (duplicate content)")
            return
        fingerprints.add(fingerprint)
        sources.append(
            Source(
                source_type=IntelSourceType.website_page,
                source_name=page_title(html) or urlparse(url).path or url,
                source_url=url,
                original_content_reference=url,
                normalized_markdown=markdown,
            )
        )
        if depth < max_depth:
            for link in links_from_html(html, url, root):
                enqueue(link, depth + 1)

    visited.add(start)
    _, homepage, error = await fetch_one(start)
    if homepage is None:
        report.errors.append(f"{start}: {error}")
        return sources, report
    accept(start, homepage, 0)

    if fetch_xml is not None:
        for page_url in await _sitemap_urls(fetch_xml, start, root, timeout, max_bytes):
            report.used_sitemap = True
            enqueue(page_url, 1)

    if search is not None and len(frontier) < 3:
        for url in await _search_urls(search, root, company_name):
            enqueue(url, 1)

    while frontier and len(sources) < max_pages:
        batch_size = min(max_pages - len(sources), parallel)
        ranked = sorted(frontier.items(), key=lambda item: (-page_score(item[0]), item[1], item[0]))
        batch = ranked[:batch_size]
        for url, _ in batch:
            frontier.pop(url, None)
            visited.add(url)
        results = await asyncio.gather(*(fetch_one(url) for url, _ in batch))
        for (url, depth), (_, html, error) in zip(batch, results):
            if html is None:
                report.errors.append(f"{url}: {error}")
                continue
            if len(sources) < max_pages:
                accept(url, html, depth)

    report.pages_fetched = len(sources)
    logger.info("crawled %s: %d pages, %d errors", start, len(sources), len(report.errors))
    return sources, report


async def _sitemap_urls(fetch_xml: FetchPage, start: str, root: str, timeout: float, max_bytes: int) -> list[str]:
    origin = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    pages: list[str] = []
    for path in SITEMAP_PATHS:
        try:
            xml = await fetch_xml(origin + path, timeout=timeout, max_bytes=max_bytes)
        except Exception:
            continue
        found, children = urls_from_sitemap(xml or "")
        pages.extend(found)
        for child in children[:MAX_CHILD_SITEMAPS]:
            if not same_site(child, root):
                continue
            try:
                child_found, _ = urls_from_sitemap(await fetch_xml(child, timeout=timeout, max_bytes=max_bytes) or "")
            except Exception:
                continue
            pages.extend(child_found)
        if pages:
            break
    return [url for url in pages if same_site(url, root)]


async def _search_urls(search: SearchClient, root: str, company_name: str) -> list[str]:
    try:
        hits = await search.search(
            f"site:{root} {company_name} about products services solutions".strip(),
            max_results=5,
            days=None,
        )
    except Exception as exc:
        logger.info("site search for %s skipped: %s", root, exc)
        return []
    return [hit.url for hit in hits if getattr(hit, "url", None) and same_site(hit.url, root)]
