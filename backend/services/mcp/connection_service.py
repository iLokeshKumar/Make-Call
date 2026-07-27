"""
connection_service.py - Connects to external MCP servers loaded from the DB registry.

Wraps the existing MCPClient from mcp_client.py with DB-aware auth resolution
and health/tool-cache management via registry_service.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from models.mcp_server import MCPServer
from services.mcp.registry_service import mark_health, upsert_tool_cache
from services.platform.mcp_client import MCPClient

logger = logging.getLogger(__name__)


def _build_headers(server: MCPServer, token: Optional[str] = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif server.auth_type == "api_key":
        key = server.config_json.get("api_key", "")
        if key:
            headers["X-Api-Key"] = key
    return headers


def connect_server(server: MCPServer, token: Optional[str] = None) -> MCPClient:
    """Return an MCPClient connected to the given server row."""
    return MCPClient(url=server.url, headers=_build_headers(server, token))


async def discover_and_cache_tools(
    session: Session,
    server: MCPServer,
    token: Optional[str] = None,
) -> int:
    """Fetch all tools from the server and save them to MCPToolCache. Returns tool count."""
    try:
        client = connect_server(server, token)
        tools = await client.list_tools()
        upsert_tool_cache(session, server.id, tools)
        mark_health(session, server.id, "healthy")
        return len(tools)
    except Exception as exc:
        logger.error("[connection_service] discover_tools(%s) failed: %s", server.name, exc)
        mark_health(session, server.id, "unhealthy")
        return 0


async def health_check_all(session: Session, company_id: int) -> dict[int, str]:
    """Ping all enabled servers for a company and update health status."""
    servers = list(session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.enabled == True,
        )
    ).all())
    results: dict[int, str] = {}
    for server in servers:
        try:
            client = connect_server(server)
            await client.list_tools()
            mark_health(session, server.id, "healthy")
            results[server.id] = "healthy"
        except Exception as exc:
            logger.warning("[connection_service] health_check(%s) failed: %s", server.name, exc)
            mark_health(session, server.id, "unhealthy")
            results[server.id] = "unhealthy"
    return results


async def call_server_tool(
    server: MCPServer,
    tool_name: str,
    arguments: dict,
    token: Optional[str] = None,
) -> dict:
    """Call a tool on the given server and return the result dict."""
    try:
        client = connect_server(server, token)
        result = await client.call_tool(tool_name, arguments)
        return {"result": result, "source": server.name, "provider": server.provider}
    except Exception as exc:
        logger.error(
            "[connection_service] %s/%s failed: %s", server.name, tool_name, exc
        )
        return {"error": str(exc), "source": server.name, "provider": server.provider}
