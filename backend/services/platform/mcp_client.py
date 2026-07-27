"""
mcp_client.py - MCP HTTP client. Connects Rio (as a client) to external MCP servers.

Any external service that exposes an MCP endpoint (Apollo, Zoho, etc.) can be added
to EXTERNAL_MCP_SERVERS. The AI agent routes tool calls prefixed with "<server>__"
to the right server automatically.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Registry — add any MCP server Rio should connect to here
# --------------------------------------------------------------------------- #
EXTERNAL_MCP_SERVERS: dict[str, dict] = {
    "apollo": {
        "url": "https://mcp.apollo.io/mcp",       # MCP endpoint (needs OAuth)
        "rest_url": "https://api.apollo.io/v1",    # REST endpoint (uses API key directly)
        "auth_env": "APOLLO_API_KEY",
        "transport": "rest",   # use REST until OAuth is configured
        "description": "Apollo.io — lead search, enrichment, sequences",
    },
    # Zoho has no public MCP server — connect via REST:
    # "zoho_crm": {
    #     "rest_url": "https://www.zohoapis.com/crm/v2",
    #     "auth_env": "ZOHO_CRM_ACCESS_TOKEN",
    #     "transport": "rest",
    #     "description": "Zoho CRM — contacts, leads, deals",
    # },
}


class MCPClient:
    """Minimal MCP JSON-RPC client over Streamable HTTP transport."""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self.url = url
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self._tools: list[dict] | None = None
        self._initialized = False

    async def _rpc(self, method: str, params: dict | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.url, json=payload, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"MCP server error: {data['error']}")
            return data.get("result")

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "rio-crm", "version": "1.0"},
        })
        self._initialized = True

    async def list_tools(self) -> list[dict]:
        if self._tools is not None:
            return self._tools
        await self.initialize()
        result = await self._rpc("tools/list")
        self._tools = result.get("tools", []) if result else []
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> Any:
        await self.initialize()
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})


def _build_headers(server: dict, auth_token: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    elif server.get("auth_env"):
        token = os.environ.get(server["auth_env"], "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


async def call_external_tool(
    prefix: str,
    tool_name: str,
    arguments: dict,
    auth_token: str | None = None,
    company_id: int | None = None,
) -> dict:
    """
    Call a tool on an external MCP server.

    prefix     — matches a key in EXTERNAL_MCP_SERVERS (e.g. "apollo")
    tool_name  — the tool's name on that server
    arguments  — tool input arguments
    auth_token — explicit token override
    company_id — if provided, looks up the stored OAuth token for this company
    """
    server = EXTERNAL_MCP_SERVERS.get(prefix)
    if not server:
        return {"error": f"No MCP server registered for prefix '{prefix}'"}

    # Resolve token: explicit > company DB > env var
    resolved_token = auth_token
    if not resolved_token and company_id and prefix == "apollo":
        try:
            from database import engine
            from sqlmodel import Session
            from routes.apollo_oauth import get_company_apollo_token
            with Session(engine) as session:
                resolved_token = get_company_apollo_token(session, company_id)
        except Exception as exc:
            logger.warning("[mcp_client] Could not load Apollo token from DB: %s", exc)

    headers = _build_headers(server, resolved_token)
    try:
        client = MCPClient(url=server["url"], headers=headers)
        result = await client.call_tool(tool_name, arguments)
        return {"result": result, "source": prefix}
    except Exception as exc:
        logger.error("[mcp_client] %s/%s failed: %s", prefix, tool_name, exc)
        return {"error": str(exc), "source": prefix}


async def list_external_tools(
    prefix: str,
    auth_token: str | None = None,
) -> list[dict]:
    """Discover all tools available on a registered MCP server."""
    server = EXTERNAL_MCP_SERVERS.get(prefix)
    if not server:
        return []

    headers = _build_headers(server, auth_token)
    try:
        client = MCPClient(url=server["url"], headers=headers)
        tools = await client.list_tools()
        return [{"server": prefix, **t} for t in tools]
    except Exception as exc:
        logger.error("[mcp_client] list_tools(%s) failed: %s", prefix, exc)
        return []


async def ping_server(prefix: str, auth_token: str | None = None) -> dict:
    """Health-check a registered MCP server. Returns status + tool count."""
    server = EXTERNAL_MCP_SERVERS.get(prefix)
    if not server:
        return {"prefix": prefix, "status": "unknown", "error": "Not registered"}

    headers = _build_headers(server, auth_token)
    try:
        client = MCPClient(url=server["url"], headers=headers)
        tools = await client.list_tools()
        return {
            "prefix": prefix,
            "url": server["url"],
            "status": "connected",
            "tool_count": len(tools),
            "description": server.get("description", ""),
        }
    except Exception as exc:
        return {
            "prefix": prefix,
            "url": server["url"],
            "status": "error",
            "error": str(exc),
        }
