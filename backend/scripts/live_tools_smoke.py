"""Live smoke test for Module 2 tools. Uses repo-root .env. Never prints secrets."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.domain.merge import merge_research
from app.domain.collected_research import CollectedResearch
from app.domain.tool_contract import ToolRequest
from app.infrastructure.tools.mlx_client import MlxClient, grounded_only
from app.infrastructure.tools.news import NewsTool
from app.infrastructure.tools.people import PeopleTool
from app.infrastructure.tools.signals import SignalsTool
from app.infrastructure.tools.tavily import TavilyClient
from app.infrastructure.tools.website_docs import WebsiteDocsTool


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"


async def _check(name: str, coro):
    try:
        detail = await coro
        print(f"PASS  {name}: {detail}")
        return True, detail
    except Exception as exc:
        print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        return False, str(exc)


async def tavily_raw() -> str:
    hits = await TavilyClient(timeout=30).search(
        "Stripe company",
        max_results=2,
        days=90,
    )
    if not hits:
        raise RuntimeError("Tavily returned 0 hits")
    sample = hits[0]
    return f"{len(hits)} hits, first title={sample.title[:80]!r}, url_set={bool(sample.url)}"


async def mlx_raw() -> str:
    settings = get_settings()
    client = MlxClient(timeout=90)
    excerpt = "Stripe is a payments company headquartered in South San Francisco."
    payload = await client.complete_json(
        "Extract only facts in the text. Return JSON with keys name, headquarters. Use null if missing. No extra keys.",
        f"Text:\n{excerpt}",
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"MLX did not return a JSON object (got {type(payload).__name__})")
    hq = grounded_only(str(payload.get("headquarters") or "") or None, excerpt)
    return (
        f"base={settings.mlx_base_url} model={settings.mlx_model} "
        f"keys={sorted(payload)} grounded_hq={hq!r}"
    )


async def run_tools() -> str:
    request = ToolRequest(
        company_name="Stripe",
        company_domain="stripe.com",
        website_url="https://stripe.com",
    )
    collected = CollectedResearch()
    parts: list[str] = []

    signals = await SignalsTool().execute(request)
    if not signals.success:
        raise RuntimeError(f"signals failed: {signals.error_code}")
    collected = merge_research(collected, signals.patch)
    supported = [
        name
        for name, field in collected.signals
        if field.status.value == "supported"
    ]
    parts.append(f"signals.supported={supported}")

    news = await NewsTool().execute(request)
    if not news.success:
        raise RuntimeError(f"news failed: {news.error_code}")
    collected = merge_research(collected, news.patch)
    parts.append(f"news.count={len(collected.news)}")

    site = await WebsiteDocsTool(timeout=30).execute(request)
    if not site.success:
        raise RuntimeError(f"website_docs failed: {site.error_code}")
    collected = merge_research(collected, site.patch)
    company_ok = [
        name
        for name, field in collected.company
        if field.status.value == "supported"
    ]
    parts.append(f"company.supported={company_ok}")

    people = await PeopleTool().execute(request)
    if not people.success:
        raise RuntimeError(f"people failed: {people.error_code}")
    collected = merge_research(collected, people.patch)
    with_email = sum(1 for person in collected.people if person.email)
    titles = [person.title or "(no title)" for person in collected.people[:3]]
    parts.append(
        f"people.count={len(collected.people)} email_present={with_email} sample_titles={titles}"
    )

    missing = collected.missing_parameters()
    parts.append(f"missing={missing}")
    return " | ".join(parts)


async def main() -> int:
    settings = get_settings()
    print("Loaded settings from .env (values masked)")
    print(f"  database_url host set: {bool(settings.database_url)}")
    print(f"  mlx_base_url: {settings.mlx_base_url}")
    print(f"  mlx_model: {settings.mlx_model}")
    print(f"  tavily_api_key: {_mask(settings.tavily_api_key)}")
    print(f"  prospeo_api_key: {_mask(settings.prospeo_api_key)}")
    print()

    results = []
    results.append(await _check("Tavily search", tavily_raw()))
    results.append(await _check("MLX extract", mlx_raw()))
    results.append(await _check("All four tools (Stripe)", run_tools()))

    passed = sum(1 for ok, _ in results if ok)
    print()
    print(f"{passed}/{len(results)} live checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
