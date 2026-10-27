from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from app.config import get_settings


class TavilyHit(BaseModel):
    title: str
    url: str
    content: str = ""
    published_at: datetime | None = None


def _parse_date(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text[: len(fmt) + 2].split("+")[0], fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class TavilyClient:
    def __init__(self, api_key: str | None = None, timeout: float = 20) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.tavily_api_key
        self.timeout = timeout

    async def search(
        self,
        query: str,
        *,
        topic: str = "general",
        max_results: int = 5,
        days: int | None = 90,
    ) -> list[TavilyHit]:
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        payload: dict[str, object] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "topic": topic,
        }
        if days is not None:
            payload["days"] = days
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
            body = response.json()
        hits: list[TavilyHit] = []
        for item in body.get("results") or []:
            hits.append(
                TavilyHit(
                    title=item.get("title") or "",
                    url=item.get("url") or "",
                    content=item.get("content") or "",
                    published_at=_parse_date(item.get("published_date")),
                )
            )
        return hits
