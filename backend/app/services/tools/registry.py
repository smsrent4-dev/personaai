"""Tool registry.

DEFAULT_TOOLS is deliberately a fixed, curated list rather than a
per-agent configurable set - every agent gets the same tools today,
and the AI's own tool-choice reasoning decides whether/when to use
them (per the spec: "without hardcoded rules"). Per-agent tool
permissions would be a natural next step (Agent.permissions already
exists as a JSON field for this) but isn't wired up yet.
"""
from app.services.ai.base import ToolDefinition
from app.services.tools.base import Tool, ToolContext
from app.services.tools.create_order_tool import CreateOrderTool
from app.services.tools.search_product_tool import SearchProductTool

DEFAULT_TOOLS: list[Tool] = [SearchProductTool(), CreateOrderTool()]


def default_tool_definitions() -> list[ToolDefinition]:
    return [tool.definition() for tool in DEFAULT_TOOLS]


async def execute_tool(tool_name: str, arguments: dict, context: ToolContext) -> dict:
    for tool in DEFAULT_TOOLS:
        if tool.name == tool_name:
            return await tool.execute(arguments, context)
    return {"error": f"Unknown tool '{tool_name}'"}
