from langchain_core.tools import BaseTool

from app.infrastructure.tools.news import as_langchain_tool as make_news_tool
from app.infrastructure.tools.people import as_langchain_tool as make_people_tool
from app.infrastructure.tools.signals import as_langchain_tool as make_signals_tool
from app.infrastructure.tools.website_docs import as_langchain_tool as make_website_docs_tool
from app.infrastructure.tools.registry import TOOL_NAMES

TOOL_NAMES = TOOL_NAMES


def research_tools(registry: dict | None = None) -> list[BaseTool]:
    """The four LangChain tools the LangGraph agent is allowed to call."""
    if registry is None:
        return [
            make_signals_tool(),
            make_news_tool(),
            make_website_docs_tool(),
            make_people_tool(),
        ]
    makers = {
        "signals": make_signals_tool,
        "news": make_news_tool,
        "website_docs": make_website_docs_tool,
        "people": make_people_tool,
    }
    return [makers[name](registry[name]) for name in TOOL_NAMES]
