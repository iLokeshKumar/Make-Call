"""
mcp_client.py - MCP HTTP client. Connects Rio (as a client) to external MCP servers.

Any external service that exposes an MCP endpoint (Apollo, Zoho, etc.) can be added
to EXTERNAL_MCP_SERVERS. The AI agent routes tool calls prefixed with "<server>__"
to the right server automatically.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
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


class MCPStdioClient:
    """MCP client over stdio transport — spawns a subprocess and speaks JSON-RPC on stdin/stdout."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self._command = self._resolve_command(command)
        self._extra_env = env or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._initialized = False
        self._tools: list[dict] | None = None
        self._msg_id = 0

    @staticmethod
    def _resolve_command(command: list[str]) -> list[str]:
        if not command:
            return command
        if sys.platform == "win32":
            resolved = shutil.which(command[0])
            if resolved:
                return [resolved] + command[1:]
        return command

    async def _ensure_process(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        merged_env = {**os.environ, **self._extra_env}
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=merged_env,
        )
        self._initialized = False

    async def _rpc(self, method: str, params: dict | None = None) -> Any:
        await self._ensure_process()
        self._msg_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }) + "\n"
        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()
        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30)
        if not line:
            raise RuntimeError("MCP stdio server closed connection unexpectedly")
        data = json.loads(line.decode())
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
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

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.close()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                self._proc.kill()


def _build_headers(server: dict, auth_token: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if server.get("transport") == "rest":
        headers["Content-Type"] = "application/json"
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        elif server.get("auth_env"):
            token = os.environ.get(server["auth_env"], "")
            if token:
                headers["X-Api-Key"] = token
    else:
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        elif server.get("auth_env"):
            token = os.environ.get(server["auth_env"], "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
    return headers


def _resolve_rest_tool_endpoint(prefix: str, tool_name: str, arguments: dict) -> tuple[str, str, dict]:
    if prefix == "apollo":
        if tool_name == "mixed_people_api_search":
            return "POST", "/mixed_people/search", arguments
        if tool_name == "contacts_search":
            return "POST", "/contacts/search", arguments
        if tool_name == "people_match":
            return "POST", "/people/match", arguments
        if tool_name == "organizations_enrich":
            return "POST", "/organizations/enrich", arguments
        if tool_name == "emailer_campaigns_add_contact_ids":
            return "POST", "/emailer_campaigns/add_contact_ids", arguments
        if tool_name == "analytics_sync_report":
            return "POST", "/analytics/sync_report", arguments
        raise ValueError(f"Apollo REST does not support tool '{tool_name}'")
    raise ValueError(f"REST transport is not implemented for provider '{prefix}'")


async def _call_rest_tool(
    prefix: str,
    server: dict,
    tool_name: str,
    arguments: dict,
    auth_token: str | None = None,
) -> dict:
    method, path, body = _resolve_rest_tool_endpoint(prefix, tool_name, arguments)
    url = server.get("rest_url", "").rstrip("/") + path
    if not url:
        return {"error": f"REST endpoint not configured for '{prefix}'"}

    headers = _build_headers(server, auth_token)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("[mcp_client] REST %s %s failed: %s", prefix, url, exc)
        return {"error": str(exc), "source": prefix}



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

    if server.get("transport") == "rest":
        result = await _call_rest_tool(prefix, server, tool_name, arguments, resolved_token)
        if isinstance(result, dict) and "error" not in result:
            return {"result": result, "source": prefix}
        return result

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
