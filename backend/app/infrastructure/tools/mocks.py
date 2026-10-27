from app.infrastructure.tools.tavily import TavilyHit


class FakeTavilyClient:
    def __init__(
        self,
        hits_by_keyword: dict[str, list[TavilyHit]] | None = None,
        default: list[TavilyHit] | None = None,
    ) -> None:
        self.hits_by_keyword = hits_by_keyword or {}
        self.default = default or []
        self.calls: list[tuple[str, dict]] = []

    async def search(self, query: str, **kwargs) -> list[TavilyHit]:
        self.calls.append((query, kwargs))
        lowered = query.lower()
        for keyword, hits in self.hits_by_keyword.items():
            if keyword.lower() in lowered:
                return hits
        return list(self.default)


class FakeMlxClient:
    def __init__(self, payload: dict | list | None = None) -> None:
        self.payload = payload if payload is not None else {}
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict | list | None:
        self.calls.append((system, user))
        return self.payload


class FakeProspeoClient:
    def __init__(
        self,
        rows: list[dict] | None = None,
        enrich_by_name: dict[str, dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.enrich_by_name = {key.lower(): value for key, value in (enrich_by_name or {}).items()}
        self.error = error
        self.calls: list[tuple[str, str | None]] = []
        self.enrich_calls: list[dict] = []

    async def search_person(self, company_name: str, domain: str | None) -> list[dict]:
        self.calls.append((company_name, domain))
        if self.error:
            raise self.error
        return list(self.rows)

    async def search_named_person(
        self,
        name: str,
        company_name: str,
        domain: str | None,
    ) -> list[dict]:
        self.calls.append((name, domain))
        if self.error:
            raise self.error
        row = self.enrich_by_name.get(name.lower())
        return [dict(row)] if row else []

    async def enrich_person(self, data: dict, *, enrich_mobile: bool = True) -> dict | None:
        self.enrich_calls.append(data)
        if self.error:
            raise self.error
        name = (data.get("full_name") or "").strip().lower()
        if name and name in self.enrich_by_name:
            return dict(self.enrich_by_name[name])
        linkedin = (data.get("linkedin_url") or "").strip().lower()
        for row in self.enrich_by_name.values():
            if linkedin and (row.get("linkedin_url") or "").strip().lower() == linkedin:
                return dict(row)
        return None
