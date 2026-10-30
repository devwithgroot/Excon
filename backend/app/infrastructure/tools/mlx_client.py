import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

NO_THINK = "/no_think"
THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)

REPAIR_SYSTEM = (
    "You repair JSON so it matches a schema. Return only the corrected JSON object. "
    "Keep every value that was already present. Do not add new facts. "
    "Use null or an empty list for anything you cannot fill."
)


class MlxClient:
    """OpenAI-compatible chat client. Not a source of verified facts."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.mlx_base_url).rstrip("/")
        self.model = model or settings.mlx_model
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds

    async def complete_text(self, system: str, user: str, *, max_tokens: int = 2048) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": f"{system}\n{NO_THINK}"},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""

    async def complete_json(self, system: str, user: str) -> dict | list | None:
        return _parse_json(await self.complete_text(system, user))

    async def complete_model(
        self,
        system: str,
        user: str,
        model_cls: type[ModelT],
        *,
        max_tokens: int = 2048,
    ) -> ModelT | None:
        """Prompt with the schema, validate with Pydantic, allow one bounded repair."""
        schema = json.dumps(model_cls.model_json_schema(), separators=(",", ":"))
        prompt = f"{system}\n\nReturn one JSON object matching this JSON schema:\n{schema}"
        raw = await self.complete_text(prompt, user, max_tokens=max_tokens)
        parsed, error = _validate(raw, model_cls)
        if parsed is not None:
            return parsed
        logger.info("llm output failed %s validation: %s", model_cls.__name__, error)
        repair_user = f"Schema:\n{schema}\n\nErrors:\n{error}\n\nJSON to repair:\n{_strip_think(raw)[:6000]}"
        repaired = await self.complete_text(REPAIR_SYSTEM, repair_user, max_tokens=max_tokens)
        parsed, error = _validate(repaired, model_cls)
        if parsed is None:
            logger.warning("llm repair for %s failed: %s", model_cls.__name__, error)
        return parsed


def _validate(raw: str, model_cls: type[ModelT]) -> tuple[ModelT | None, str]:
    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        return None, "Output was not a JSON object."
    try:
        return model_cls.model_validate(payload), ""
    except ValidationError as exc:
        return None, str(exc)[:2000]


def _strip_think(raw: str) -> str:
    return THINK_BLOCK.sub("", raw).strip()


def _parse_json(raw: str) -> dict | list | None:
    text = _strip_think(raw)
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _first_json_value(text)
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _first_json_value(text: str) -> dict | list | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
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
