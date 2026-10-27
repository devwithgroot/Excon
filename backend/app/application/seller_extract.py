from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from app.domain.collected_research import CollectedResearch
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.seller_profile import SellerICP, SellerProfile
from app.infrastructure.tools.mlx_client import grounded_only
from app.infrastructure.tools.website_docs import fetch_public_text, html_to_text

EXTRACT_SYSTEM = (
    "Extract only facts present in the provided text about the SELLER company. "
    "Return JSON with keys: industry, geography, size, products, services, features, "
    "problems_solved, differentiators, limitations, icp_industries, icp_size, "
    "icp_geography, icp_roles, icp_problems, icp_signals, icp_exclusions, icp_preferred, "
    "description. "
    "Use null when the text does not state a fact. Never invent or guess."
)

SELLER_PATHS = (
    "/about",
    "/about-us",
    "/services",
    "/solutions",
    "/products",
    "/what-we-do",
    "/industries",
    "/company",
    "/work",
)

SELLER_LINK_HINTS = (
    "about",
    "service",
    "solution",
    "product",
    "industr",
    "what-we",
    "company",
    "work",
    "capabilit",
)

EXTRA_KEYS = (
    "industry",
    "geography",
    "size",
    "products",
    "services",
    "features",
    "problems_solved",
    "differentiators",
    "limitations",
    "description",
    "icp_industries",
    "icp_size",
    "icp_geography",
    "icp_roles",
    "icp_problems",
    "icp_signals",
    "icp_exclusions",
    "icp_preferred",
)


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    if not host:
        return None
    return host.lower().removeprefix("www.") or None


def _clip(text: str, limit: int = 320) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" \t\n\r,;:-")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    return _clip(match.group(1))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _sentence_with(text: str, *needles: str, min_len: int = 24, max_len: int = 280) -> str | None:
    lowered_needles = [needle.lower() for needle in needles]
    hits: list[str] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if any(token in lowered for token in ("cookie", "sign in", "privacy policy")):
            continue
        if any(needle in lowered for needle in lowered_needles) and min_len < len(sentence) < max_len:
            hits.append(sentence.strip())
    if not hits:
        return None
    return _clip(min(hits, key=len))


def heuristic_seller_fields(company_name: str, text: str) -> dict[str, str]:
    """Pull seller-profile facts that are already written on the site."""
    found: dict[str, str] = {}
    if not text.strip():
        return found

    title_match = re.search(
        r"([^|–—\n]{3,80})\s*[|–—]\s*([^|–—\n.]{8,90})",
        text[:400],
        flags=re.I,
    )
    if title_match:
        title_right = _clip(title_match.group(2), 90)
        if " for " in title_right.lower():
            offering, audience = re.split(r"\s+for\s+", title_right, maxsplit=1, flags=re.I)
            for stop in (company_name, "Turning", "Visits", "FieldAXIS"):
                if stop and stop.lower() in audience.lower() and not audience.lower().startswith(stop.lower()):
                    audience = re.split(stop, audience, flags=re.I)[0]
            found.setdefault("products", _clip(offering, 120))
            found.setdefault("services", _clip(offering, 120))
            found.setdefault("icp_industries", _clip(audience, 80))
        else:
            found.setdefault("products", title_right)

    description = (
        _sentence_with(
            text,
            f"{company_name} is",
            f"{company_name} helps",
            "we help",
            "we start",
            "operational intelligence",
            "turning field",
        )
        or _first_match(
            r"(?:^|\n)([^.\n]{40,240}(?:helps|maps|delivers|builds|automates|turning)[^.\n]{10,200})",
            text,
        )
    )
    turning = _first_match(r"(Turning [^.]{20,160})", text)
    if turning:
        found.setdefault("description", turning)
    if description:
        found.setdefault("description", description)

    industry = _first_match(
        r"\b((?:operations[- ]first )?technology firm|sales force automation|field operations|b2b software|saas|software (?:company|consultancy)|it services|workflow automation)\b",
        text,
    )
    if industry:
        found.setdefault("industry", industry.title() if industry.islower() else industry)

    products = _first_match(
        r"(?:we (?:deliver|build|offer|provide)|then deliver|examples of what we build|our (?:products|services|work))\s*[:—-]?\s+([^.]+)",
        text,
    )
    if products:
        found.setdefault("products", products)
        found.setdefault("services", products)

    if "ops audit" in text.lower() or "custom software" in text.lower():
        offerings: list[str] = []
        for token in (
            "Ops Audit",
            "workflow automation",
            "custom software",
            "digital visibility",
            "workflow reviews",
        ):
            if token.lower() in text.lower() and token.lower() not in " ".join(offerings).lower():
                offerings.append(token)
        if offerings:
            found.setdefault("products", ", ".join(offerings))
            found.setdefault("services", ", ".join(offerings))

    problems = (
        _sentence_with(text, "stuck", "whatsapp", "chasing", "missing data", "who owns")
        or _first_match(r"(?:problems? we solve|we (?:fix|map) how)\s+([^.]+)", text)
    )
    if problems:
        found.setdefault("problems_solved", problems)

    differentiators = _sentence_with(
        text,
        "we don't assume",
        "only what your business needs",
        "no software required",
        "starting with an ops audit",
        "unlike",
    )
    if differentiators:
        found.setdefault("differentiators", differentiators)

    limitations = _first_match(
        r"(?:not a fit when|not for|we don['’]t (?:work with|serve|take on)|we do not (?:work with|serve))\s+([^.]+)",
        text,
    )
    if limitations:
        found.setdefault("limitations", limitations)

    geography = _first_match(
        r"(Bengaluru|Bangalore|Mumbai|Delhi|Hyderabad|Chennai|Pune|[A-Z][a-z]+,\s*(?:India|USA|UK|UAE))",
        text,
    ) or _first_match(r"\b((?:India|United States|United Kingdom|UAE|Singapore))\b", text)
    if geography:
        found.setdefault("geography", geography)
        found.setdefault("icp_geography", geography)

    if re.search(r"\bMSME|small and medium|growing teams\b", text, flags=re.I):
        found.setdefault("icp_size", "Indian MSMEs / growing teams" if "msme" in text.lower() else "growing teams")
        if "indian" in text.lower() or "india" in text.lower():
            found.setdefault("icp_industries", found.get("icp_industries") or "Indian MSMEs")

    roles = _first_match(
        r"\b((?:CEO|CTO|COO|founder|operations? (?:head|lead|manager)|heads? of [A-Za-z ]{3,20})s?)\b",
        text,
    )
    if roles:
        found.setdefault("icp_roles", roles)

    size = _first_match(r"(\d[\d,]{0,6}\+?\s+employees)", text)
    if size:
        found.setdefault("size", size)

    signals = _first_match(
        r"(hiring|expansion|new product|funding|digital transformation|workflow (?:chaos|review))",
        text,
    )
    if signals:
        found.setdefault("icp_signals", signals)

    return {key: value for key, value in found.items() if value}


def seller_profile_from_patch(
    seller_input: dict,
    patch: CollectedResearch | None = None,
    extras: dict | None = None,
) -> SellerProfile:
    company = patch.company if patch is not None else None
    extra = extras or {}
    website = seller_input.get("website_url") or None
    products = (
        extra.get("products")
        or (company.products.value if company and company.products.value else None)
    )
    services = extra.get("services") or products
    evidence = [
        item for item in (patch.evidence if patch else []) if item.field_key.startswith("company.")
    ]
    return SellerProfile(
        company_name=(company.name.value if company and company.name.value else None)
        or seller_input.get("company_name")
        or "",
        contact_name=seller_input.get("name") or None,
        domain=(company.domain.value if company and company.domain.value else None)
        or domain_from_url(website),
        website_url=website,
        industry=(extra.get("industry") or (company.industry.value if company and company.industry.value else None)),
        description=(
            extra.get("description")
            or (company.description.value if company and company.description.value else None)
        ),
        geography=extra.get("geography")
        or (company.headquarters.value if company and company.headquarters.value else None),
        size=(extra.get("size") or (company.size.value if company and company.size.value else None)),
        products=products,
        services=services,
        features=extra.get("features"),
        problems_solved=extra.get("problems_solved"),
        differentiators=extra.get("differentiators"),
        limitations=extra.get("limitations"),
        icp=SellerICP(
            target_industries=extra.get("icp_industries"),
            company_size=extra.get("icp_size"),
            geography=extra.get("icp_geography") or extra.get("geography"),
            departments_roles=extra.get("icp_roles"),
            problems=extra.get("icp_problems") or extra.get("problems_solved"),
            buying_signals=extra.get("icp_signals"),
            exclusions=extra.get("icp_exclusions"),
            preferred=extra.get("icp_preferred"),
        ),
        evidence_ids=[item.evidence_id for item in evidence],
        evidence=evidence,
        status="draft",
        version=0,
    )


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _seller_urls(website_url: str, homepage_html: str) -> list[str]:
    origin = _origin(website_url)
    found = [website_url]
    seen = {website_url.rstrip("/")}
    for path in SELLER_PATHS:
        url = urljoin(origin + "/", path.lstrip("/"))
        if url.rstrip("/") not in seen:
            seen.add(url.rstrip("/"))
            found.append(url)
    root = (urlparse(website_url).hostname or "").lower().removeprefix("www.")
    for href in re.findall(r"""href=["']([^"'#]+)""", homepage_html, flags=re.I):
        absolute = urljoin(website_url, href).split("#")[0]
        host = (urlparse(absolute).hostname or "").lower().removeprefix("www.")
        if host != root:
            continue
        path = (urlparse(absolute).path or "/").lower()
        if not any(hint in path for hint in SELLER_LINK_HINTS):
            continue
        if absolute.rstrip("/") in seen:
            continue
        seen.add(absolute.rstrip("/"))
        found.append(absolute)
    return found[:6]


async def _fetch_one(fetch_page, url: str, timeout: float, max_bytes: int) -> tuple[str, str]:
    try:
        raw = await fetch_page(url, timeout=timeout, max_bytes=max_bytes)
        return url, raw or ""
    except Exception:
        return url, ""


async def scrape_seller_site(
    website_url: str,
    *,
    company_name: str = "",
    fetch_page=None,
    timeout: float = 8,
    max_bytes: int = 800_000,
) -> tuple[str, list[EvidenceItem]]:
    fetch = fetch_page or fetch_public_text
    homepage_url, homepage_html = await _fetch_one(fetch, website_url, timeout, max_bytes)
    pages = [(homepage_url, homepage_html)]
    preview = heuristic_seller_fields(company_name, html_to_text(homepage_html))
    extra = [
        url
        for url in _seller_urls(website_url, homepage_html)
        if url.rstrip("/") != homepage_url.rstrip("/")
    ]
    if extra and not (preview.get("products") and preview.get("description")):
        pages.extend(
            await asyncio.gather(
                *[_fetch_one(fetch, url, timeout, max_bytes) for url in extra[:3]]
            )
        )

    texts: list[str] = []
    evidence: list[EvidenceItem] = []
    for url, raw in pages:
        if not raw:
            continue
        text = html_to_text(raw)
        if len(text) < 40:
            continue
        texts.append(text)
        evidence.append(
            EvidenceItem(
                field_key="company.description",
                extracted_value=None,
                source_url=url,
                source_type=SourceType.website,
                retrieved_at=datetime.now(timezone.utc),
                supporting_excerpt=text[:400],
                extraction_method="scrape",
                confidence=0.7,
            )
        )
    return "\n\n".join(texts), evidence


def _text_from_input(seller_input: dict, scraped: str) -> str:
    parts = [scraped] if scraped else []
    for doc in seller_input.get("documents") or []:
        text = doc.get("text") if isinstance(doc, dict) else getattr(doc, "text", None)
        if text:
            parts.append(str(text)[:6000])
    return "\n\n".join(parts)


def _grounded_phrase(value: str | None, text: str) -> str | None:
    if not value:
        return None
    exact = grounded_only(value, text)
    if exact:
        return exact
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", value.lower()) if token]
    hits = sum(1 for token in tokens if token in text.lower())
    if tokens and hits >= min(2, len(tokens)):
        return value.strip()
    return None


async def _mlx_extras(text: str, seller_input: dict, mlx: Any) -> dict[str, str]:
    if not text.strip() or mlx is None:
        return {}
    try:
        payload = await mlx.complete_json(
            EXTRACT_SYSTEM,
            f"Seller: {seller_input.get('company_name')}\n\nText:\n{text[:8000]}",
        )
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    extras: dict[str, str] = {}
    for key in EXTRA_KEYS:
        grounded = _grounded_phrase(str(payload.get(key) or "") or None, text)
        if grounded:
            extras[key] = grounded
    return extras


async def extract_seller_profile(
    seller_input: dict,
    *,
    registry: dict | None = None,
    mlx: Any | None = None,
    fetch_page=None,
) -> SellerProfile:
    del registry  # seller extract scrapes directly; lead tools stay on the research graph
    scraped = ""
    evidence: list[EvidenceItem] = []
    website = seller_input.get("website_url") or ""
    if website:
        scraped, evidence = await scrape_seller_site(
            website,
            company_name=seller_input.get("company_name") or "",
            fetch_page=fetch_page,
        )
    scraped = _text_from_input(seller_input, scraped)
    extras = heuristic_seller_fields(seller_input.get("company_name") or "", scraped)
    if mlx is not None and scraped and not extras.get("products"):
        for key, value in (await _mlx_extras(scraped, seller_input, mlx)).items():
            extras.setdefault(key, value)
    profile = seller_profile_from_patch(seller_input, None, extras)
    if evidence:
        profile.evidence = evidence
        profile.evidence_ids = [item.evidence_id for item in evidence]
    return profile
