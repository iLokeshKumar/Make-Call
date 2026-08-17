from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Awaitable

from fastmcp import FastMCP

from mcp_tools.registry import ToolRegistry
from mcp_tools.registration import populate
from mcp_tools.router import ToolRouter

logger = logging.getLogger(__name__)


class AsyncMCPServer:
    def __init__(self, name: str = "Rio CRM Navigator"):
        self.mcp = FastMCP(name)
        self.registry = ToolRegistry()
        populate(self.registry)
        self.router = ToolRouter(self.registry)

    def register_resource(self, uri: str, handler: Callable[..., Any]) -> None:
        self.mcp.resource(uri)(handler)

    def register_tool(self, tool_name: str) -> None:
        spec = self.registry.get_spec(tool_name)
        executor = self.registry.get_executor(tool_name)

        @self.mcp.tool(
            name=spec.name,
            description=self._render_description(spec),
        )
        async def _tool_wrapper(**kwargs):
            return await executor(**kwargs)

    def register_tools_for_category(self, category: str) -> None:
        for tool_name in self.registry.list_by_category(category):
            self.register_tool(tool_name)

    def _render_description(self, spec) -> str:
        return "\n".join([
            spec.description,
            "",
            "Use this when:",
            *[f"- {x}" for x in spec.when_to_use],
            "",
            "Do not use this when:",
            *[f"- {x}" for x in spec.when_not_to_use],
            "",
            f"Returns: {spec.returns}",
        ])

    def get_asgi_app(self):
        return self.mcp.http_app(transport="sse")