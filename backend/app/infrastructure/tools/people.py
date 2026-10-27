"""LangChain tool: people. Called by the LangGraph research agent."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from langchain_core.tools import StructuredTool

from app.config import get_settings
from app.domain.collected_research import CollectedResearch, PersonRecord
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.tool_contract import ToolRequest, ToolResult
from app.infrastructure.tools.tavily import TavilyClient, TavilyHit

PROSPEO_SEARCH_PERSON = "https://api.prospeo.io/search-person"
PROSPEO_ENRICH_PERSON = "https://api.prospeo.io/enrich-person"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LINKEDIN_RE = re.compile(
    r"https?://(?:[\w-]+\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?",
    re.I,
)
NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z'.-]+){1,2})\b")
ROLE_HINTS = (
    "ceo",
    "chief executive",
    "founder",
    "co-founder",
    "cofounder",
    "owner",
    "managing director",
    "managing-director",
    " md ",
    "director",
    "president",
    "chairman",
    "chairwoman",
    "cto",
    "cfo",
    "coo",
    "decision maker",
    "vice president",
    "vp ",
)
NAME_STOP = {
    "linkedin",
    "wikipedia",
    "official",
    "about",
    "company",
    "profile",
    "united states",
    "new york",
    "san francisco",
    "south san",
}


@dataclass
class PersonCandidate:
    name: str
    title: str | None = None
    linkedin_url: str | None = None
    source_url: str | None = None
    excerpt: str = ""


class ProspeoClient:
    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.prospeo_api_key
        self.timeout = timeout if timeout is not None else settings.http_timeout_seconds
        self.page_size = settings.prospeo_page_size

    async def search_person(self, company_name: str, domain: str | None) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("PROSPEO_API_KEY is not set")
        payload = build_search_payload(company_name, domain)
        return await self._post_search(payload)

    async def search_named_person(
        self,
        name: str,
        company_name: str,
        domain: str | None,
    ) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("PROSPEO_API_KEY is not set")
        payload = build_named_search_payload(name, company_name, domain)
        return await self._post_search(payload)

    async def enrich_person(self, data: dict, *, enrich_mobile: bool = True) -> dict | None:
        if not self.api_key:
            raise RuntimeError("PROSPEO_API_KEY is not set")
        payload = {"data": {key: value for key, value in data.items() if value}, "enrich_mobile": enrich_mobile}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                PROSPEO_ENRICH_PERSON,
                json=payload,
                headers={"X-KEY": self.api_key, "Content-Type": "application/json"},
            )
            body = _json_body(response)
            code = _error_code(body, response.status_code)
            if code in {"NO_RESULTS", "INSUFFICIENT_CREDITS"}:
                return None
            if code == "INVALID_API_KEY":
                raise RuntimeError("PROSPEO_API_KEY is not set")
            if code or response.is_error:
                raise RuntimeError(code or f"prospeo_http_{response.status_code}")
        if not isinstance(body, dict):
            return None
        person = body.get("person")
        if isinstance(person, dict):
            if isinstance(body.get("company"), dict):
                person = dict(person)
                person["_company"] = body["company"]
            return person
        return None

    async def _post_search(self, payload: dict) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                PROSPEO_SEARCH_PERSON,
                json=payload,
                headers={"X-KEY": self.api_key, "Content-Type": "application/json"},
            )
            body = _json_body(response)
            code = _error_code(body, response.status_code)
            if code == "NO_RESULTS":
                return []
            if code == "INVALID_API_KEY":
                raise RuntimeError("PROSPEO_API_KEY is not set")
            if code or response.is_error:
                raise RuntimeError(code or f"prospeo_http_{response.status_code}")
        return _result_rows(body)[: self.page_size]


class PeopleTool:
    name = "people"
    version = "1"
    fulfills = ("people",)

    def __init__(
        self,
        client: ProspeoClient | None = None,
        tavily: TavilyClient | None = None,
        enrich_limit: int | None = None,
        enrich_mobile: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.client = client or ProspeoClient()
        self.tavily = tavily if tavily is not None else TavilyClient()
        self.enrich_limit = enrich_limit if enrich_limit is not None else settings.prospeo_enrich_limit
        self.enrich_mobile = (
            enrich_mobile if enrich_mobile is not None else settings.prospeo_enrich_mobile
        )

    async def execute(self, request: ToolRequest) -> ToolResult:
        retrieved_at = datetime.now(timezone.utc)
        try:
            hits: list[TavilyHit] = []
            queries = [
                f'{request.company_name} (CEO OR founder OR "managing director" OR owner) site:linkedin.com/in',
            ]
            if request.focus not in {"linkedin", "people"}:
                queries.append(
                    f"{request.company_name} CEO founder owner director "
                    '"managing director" MD president chairman'
                )
            for query in queries:
                hits.extend(await self.tavily.search(query, max_results=5, days=None))
            candidates = extract_decision_makers(hits, request.company_name)
        except RuntimeError:
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code="people_not_configured",
                retryable=False,
            )
        except Exception:
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code="people_provider_error",
                retryable=True,
            )

        people: list[PersonRecord] = []
        evidence: list[EvidenceItem] = []
        for candidate in candidates[: self.enrich_limit]:
            row = await self._lookup(candidate, request)
            record, item = _map_person(
                row,
                retrieved_at,
                fallback=candidate,
                extraction_method="web+prospeo" if row.get("person_id") or row.get("email") else "web_search",
            )
            if record is None or item is None:
                continue
            people.append(record)
            evidence.append(item)

        return ToolResult(
            success=True,
            tool_name=self.name,
            patch=CollectedResearch(people=people, evidence=evidence),
            evidence=evidence,
        )

    async def _lookup(self, candidate: PersonCandidate, request: ToolRequest) -> dict:
        data = {
            "full_name": candidate.name,
            "linkedin_url": candidate.linkedin_url,
            "company_name": request.company_name,
            "company_website": request.company_domain,
        }
        try:
            enriched = await self.client.enrich_person(data, enrich_mobile=self.enrich_mobile)
        except Exception:
            enriched = None
        if enriched and _enrich_matches_company(enriched, request):
            return enriched
        try:
            named = await self.client.search_named_person(
                candidate.name,
                request.company_name,
                request.company_domain,
            )
        except Exception:
            named = []
        if named:
            try:
                person_id = named[0].get("person_id")
                if person_id:
                    from_id = await self.client.enrich_person(
                        {"person_id": person_id},
                        enrich_mobile=self.enrich_mobile,
                    )
                    if from_id and _enrich_matches_company(from_id, request):
                        return from_id
            except Exception:
                pass
            if _enrich_matches_company(named[0], request):
                return named[0]
        return {}


def extract_decision_makers(hits: list[TavilyHit], company_name: str) -> list[PersonCandidate]:
    found: list[PersonCandidate] = []
    seen: set[str] = set()
    company = company_name.lower()
    for hit in hits:
        blob = f"{hit.title} {hit.content}"
        if company not in blob.lower() and "linkedin.com/in/" not in (hit.url or "").lower():
            continue
        if not _has_role(blob):
            continue
        linkedin = _clean_linkedin(hit.url) if "linkedin.com/in/" in (hit.url or "").lower() else None
        if not linkedin:
            match = LINKEDIN_RE.search(blob)
            linkedin = _clean_linkedin(match.group(0)) if match else None
        name = _name_from_text(hit.title, company_name) or _name_from_text(hit.content, company_name)
        if not name:
            continue
        key = (linkedin or name).lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(
            PersonCandidate(
                name=name,
                title=_title_from_text(blob),
                linkedin_url=linkedin,
                source_url=hit.url or None,
                excerpt=(hit.content or hit.title)[:400],
            )
        )
    return found


def _has_role(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(role in lowered for role in ROLE_HINTS)


def _name_from_text(text: str, company_name: str) -> str | None:
    cleaned = re.sub(r"\s*\|\s*LinkedIn.*$", "", text, flags=re.I)
    cleaned = cleaned.split(" - ")[0].split(",")[0].split(" at ")[0]
    match = NAME_RE.search(cleaned)
    if not match:
        return None
    name = match.group(1).strip()
    if name.lower() == company_name.lower() or name.lower() in NAME_STOP:
        return None
    if any(part.lower() in NAME_STOP for part in (name,)):
        return None
    return name


def _title_from_text(text: str) -> str | None:
    for role in (
        "Co-Founder",
        "Managing Director",
        "Chief Executive Officer",
        "Chief Executive",
        "Vice President",
        "CEO",
        "CTO",
        "CFO",
        "COO",
        "Founder",
        "President",
        "Chairman",
        "Director",
        "VP",
        "MD",
        "Owner",
    ):
        if re.search(rf"\b{re.escape(role)}\b", text, flags=re.I):
            return role
    return None


def _enrich_matches_company(row: dict, request: ToolRequest) -> bool:
    company = row.get("_company") if isinstance(row.get("_company"), dict) else {}
    website = ""
    name = ""
    if isinstance(company, dict):
        website = str(company.get("website") or company.get("domain") or "").lower()
        name = str(company.get("name") or "").lower()
    history = row.get("job_history")
    if isinstance(history, list):
        for job in history:
            if isinstance(job, dict) and job.get("current"):
                name = name or str(job.get("company_name") or "").lower()
    domain = (request.company_domain or "").lower().removeprefix("www.")
    wanted = request.company_name.lower()
    if domain and website:
        host = website.replace("https://", "").replace("http://", "").split("/")[0].removeprefix("www.")
        if host and domain not in host and host not in domain:
            return False
    if name and wanted not in name and name not in wanted:
        if domain and website:
            return True
        return False
    return True


def build_search_payload(company_name: str, domain: str | None, page: int = 1) -> dict:
    if domain:
        host = domain.lower().removeprefix("www.").split("/")[0]
        company = {"websites": {"include": [host]}}
    else:
        company = {"names": {"include": [company_name]}}
    return {"page": page, "filters": {"company": company}}


def build_named_search_payload(
    name: str,
    company_name: str,
    domain: str | None,
    page: int = 1,
) -> dict:
    payload = build_search_payload(company_name, domain, page=page)
    payload["filters"]["person_name"] = {"include": [name]}
    return payload


def _json_body(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return {}


def _error_code(body: object, status_code: int) -> str | None:
    if isinstance(body, dict) and body.get("error") not in {None, False}:
        code = body.get("error_code")
        if isinstance(code, str) and code:
            return code
        if status_code >= 400:
            return f"prospeo_http_{status_code}"
    if status_code >= 400:
        return f"prospeo_http_{status_code}"
    return None


def _result_rows(body: object) -> list[dict]:
    if isinstance(body, list):
        return [_unwrap_person(row) for row in body if isinstance(row, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("results", "people", "contacts"):
        value = body.get(key)
        if isinstance(value, list):
            return [_unwrap_person(row) for row in value if isinstance(row, dict)]
    data = body.get("data")
    if isinstance(data, list):
        return [_unwrap_person(row) for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return _result_rows(data)
    return []


def _unwrap_person(row: dict) -> dict:
    person = row.get("person")
    if isinstance(person, dict):
        copied = dict(person)
        if isinstance(row.get("company"), dict):
            copied["_company"] = row["company"]
        return copied
    return row


def _map_person(
    row: dict,
    retrieved_at: datetime,
    fallback: PersonCandidate | None = None,
    extraction_method: str = "prospeo",
) -> tuple[PersonRecord | None, EvidenceItem | None]:
    name = _first_str(row, "full_name", "name")
    if not name:
        first = _first_str(row, "first_name")
        last = _first_str(row, "last_name")
        if first and last:
            name = f"{first} {last}"
    if not name and fallback:
        name = fallback.name
    if not name:
        return None, None
    title = _first_str(row, "current_job_title", "job_title", "title") or (fallback.title if fallback else None)
    role = _first_str(row, "headline", "summary", "role", "role_description")
    email = _clean_email(
        _revealed_contact(row.get("email"), "email")
        or _first_str(row, "email", "work_email", "professional_email")
    )
    phone = _revealed_contact(row.get("mobile"), "mobile") or _first_str(
        row, "phone", "phone_number", "mobile_phone"
    )
    if phone and "*" in phone:
        phone = None
    linkedin = _clean_linkedin(_first_str(row, "linkedin_url", "linkedin"))
    if not linkedin and fallback:
        linkedin = fallback.linkedin_url
    excerpt = ", ".join(part for part in (name, title, role) if part)
    if fallback and fallback.excerpt:
        excerpt = f"{excerpt}. {fallback.excerpt}"[:400]
    item = EvidenceItem(
        field_key="people",
        extracted_value=name,
        source_url=linkedin or (fallback.source_url if fallback else None),
        source_type=SourceType.people,
        retrieved_at=retrieved_at,
        supporting_excerpt=excerpt[:400],
        extraction_method=extraction_method,
        confidence=0.75 if email or phone else 0.6,
    )
    record = PersonRecord(
        name=name,
        title=title,
        role_description=role,
        email=email,
        phone=phone,
        linkedin_url=linkedin,
        evidence_id=item.evidence_id,
    )
    return record, item


def _revealed_contact(raw: object, key: str) -> str | None:
    if not isinstance(raw, dict) or raw.get("revealed") is not True:
        return None
    value = raw.get(key)
    if isinstance(value, str) and value.strip() and "*" not in value:
        return value.strip()
    return None


def _first_str(row: dict, *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clean_email(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if EMAIL_RE.match(candidate) and "*" not in candidate:
        return candidate
    return None


def _clean_linkedin(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate.rstrip("/")
    if candidate.startswith("linkedin.com") or candidate.startswith("www.linkedin.com"):
        return f"https://{candidate}".rstrip("/")
    if candidate.startswith("/in/"):
        return f"https://www.linkedin.com{candidate}".rstrip("/")
    return None


def as_langchain_tool(instance: "PeopleTool | None" = None) -> StructuredTool:
    from app.tools.lc_tool import as_research_tool

    return as_research_tool(
        name="people",
        description=(
            "Find decision-makers via web search, then enrich name, title, "
            "LinkedIn, email, and phone. Does not invent contacts."
        ),
        worker=instance or PeopleTool(),
    )


people_tool = as_langchain_tool
