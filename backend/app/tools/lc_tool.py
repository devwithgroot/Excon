import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.domain.collected_research import ParameterStatus
from app.domain.tool_contract import DocumentInput, ToolRequest, ToolResult


class ToolCallArgs(BaseModel):
    company_name: str = Field(description="Company or lead name to research")
    company_domain: str = Field(default="", description="Root domain if known, e.g. acme.com")
    website_url: str = Field(default="", description="Official website URL if known")
    focus: str = Field(
        default="",
        description="Optional single field to target on a retry, e.g. funding or size",
    )
    documents: list[DocumentInput] = Field(
        default_factory=list,
        description="Optional extracted document texts (filename + text)",
    )


def as_research_tool(name: str, description: str, worker) -> StructuredTool:
    """Turn a Pydantic adapter into a LangChain tool the LangGraph agent can call."""

    async def _run(
        company_name: str,
        company_domain: str = "",
        website_url: str = "",
        focus: str = "",
        documents: list | None = None,
    ) -> str:
        docs: list[DocumentInput] = []
        for item in documents or []:
            if isinstance(item, DocumentInput):
                docs.append(item)
            elif isinstance(item, dict):
                docs.append(
                    DocumentInput(
                        filename=str(item.get("filename") or "upload.txt"),
                        text=item.get("text"),
                    )
                )
        result: ToolResult = await worker.execute(
            ToolRequest(
                company_name=company_name,
                company_domain=company_domain or None,
                website_url=website_url or None,
                documents=docs,
                focus=focus or None,
            )
        )
        return json.dumps(
            {
                "tool_name": name,
                "success": result.success,
                "error_code": result.error_code,
                "patch": result.patch.model_dump(mode="json"),
                "summary": _summarize(result),
            }
        )

    return StructuredTool.from_function(
        coroutine=_run,
        name=name,
        description=description,
        args_schema=ToolCallArgs,
    )


def _summarize(result: ToolResult) -> dict:
    patch = result.patch
    return {
        "success": result.success,
        "error_code": result.error_code,
        "supported_company": [
            name for name, field in patch.company if field.status == ParameterStatus.supported
        ],
        "supported_signals": [
            name for name, field in patch.signals if field.status == ParameterStatus.supported
        ],
        "news_count": len(patch.news),
        "people_count": len(patch.people),
        "people_preview": [
            {"name": person.name, "title": person.title, "has_email": bool(person.email)}
            for person in patch.people[:5]
        ],
    }
