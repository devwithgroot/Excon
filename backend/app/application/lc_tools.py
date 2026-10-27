from app.tools import research_tools
from app.domain.collected_research import CollectedResearch

langchain_research_tools = research_tools


def empty_collected_dump() -> dict:
    return CollectedResearch().model_dump(mode="json")
