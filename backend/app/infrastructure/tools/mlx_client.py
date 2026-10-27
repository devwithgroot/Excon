import json
import re

import httpx

from app.config import get_settings


class MlxClient:
    """OpenAI-compatible chat client. Not a source of verified facts."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 45,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.mlx_base_url).rstrip("/")
        self.model = model or settings.mlx_model
        self.timeout = timeout

    async def complete_json(self, system: str, user: str) -> dict | list | None:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return _parse_json(content)


def _parse_json(raw: str) -> dict | list | None:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def grounded_only(value: str | None, excerpt: str) -> str | None:
    if not value:
        return None
    haystack = excerpt.lower()
    if value.lower() in haystack:
        return value
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", value.lower()) if token]
    if tokens and all(token in haystack for token in tokens[:3]):
        return value
    return None
