from app.domain.tool_contract import ResearchTool
from app.infrastructure.tools.news import NewsTool
from app.infrastructure.tools.people import PeopleTool
from app.infrastructure.tools.signals import SignalsTool
from app.infrastructure.tools.website_docs import WebsiteDocsTool

TOOL_NAMES = ("signals", "news", "website_docs", "people")


def default_registry(**overrides: ResearchTool) -> dict[str, ResearchTool]:
    built: dict[str, ResearchTool] = {
        "signals": overrides.get("signals") or SignalsTool(),
        "news": overrides.get("news") or NewsTool(),
        "website_docs": overrides.get("website_docs") or WebsiteDocsTool(),
        "people": overrides.get("people") or PeopleTool(),
    }
    return built


def get_tool(name: str, registry: dict[str, ResearchTool] | None = None) -> ResearchTool:
    tools = registry if registry is not None else default_registry()
    try:
        return tools[name]
    except KeyError as exc:
        raise KeyError(f"unknown tool: {name}") from exc
