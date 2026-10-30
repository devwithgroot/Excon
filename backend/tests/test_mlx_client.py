from pydantic import BaseModel

from app.infrastructure.tools.mlx_client import MlxClient, _parse_json, grounded_only


def test_grounded_only_keeps_excerpt_facts() -> None:
    excerpt = "Acme is headquartered in Austin and sells industrial widgets."
    assert grounded_only("Austin", excerpt) == "Austin"
    assert grounded_only("industrial widgets", excerpt) == "industrial widgets"


def test_grounded_only_drops_invented_facts() -> None:
    excerpt = "Acme sells bolts."
    assert grounded_only("quantum computing", excerpt) is None
    assert grounded_only("Series B", excerpt) is None
    assert grounded_only("", excerpt) is None


def test_parse_json_accepts_fenced_object() -> None:
    assert _parse_json('```json\n{"name": "Acme"}\n```') == {"name": "Acme"}
    assert _parse_json("not json") is None
    assert _parse_json('"just a string"') is None


def test_parse_json_strips_qwen_think_blocks() -> None:
    raw = '<think>\nThe user wants JSON.\n</think>\n\n{"name": "Acme"}'
    assert _parse_json(raw) == {"name": "Acme"}
    assert _parse_json("<think>never closed") is None


def test_parse_json_finds_object_inside_prose() -> None:
    assert _parse_json('Sure! Here it is: {"name": "Acme"} hope that helps') == {"name": "Acme"}


class _Pick(BaseModel):
    products: list[str]


class _ScriptedClient(MlxClient):
    def __init__(self, replies: list[str]) -> None:
        super().__init__(base_url="http://unused", model="test")
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    async def complete_text(self, system: str, user: str, *, max_tokens: int = 2048) -> str:
        self.calls.append((system, user))
        return self.replies.pop(0)


async def test_complete_model_validates_first_reply() -> None:
    client = _ScriptedClient(['{"products": ["CRM"]}'])
    result = await client.complete_model("sys", "user", _Pick)
    assert result == _Pick(products=["CRM"])
    assert len(client.calls) == 1


async def test_complete_model_repairs_once_then_gives_up() -> None:
    client = _ScriptedClient(['{"products": "CRM"}', '{"products": ["CRM"]}'])
    assert await client.complete_model("sys", "user", _Pick) == _Pick(products=["CRM"])
    assert len(client.calls) == 2

    failing = _ScriptedClient(["nope", "still nope"])
    assert await failing.complete_model("sys", "user", _Pick) is None
    assert len(failing.calls) == 2
