from app.infrastructure.tools.mlx_client import _parse_json, grounded_only


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
