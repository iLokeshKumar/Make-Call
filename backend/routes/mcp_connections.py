"""
mcp_connections.py - API routes for managing Rio's external MCP server connections.

Static proxy endpoints (unchanged):
  GET  /mcp-connections/servers          — list all registered servers + status
  GET  /mcp-connections/servers/{prefix} — ping one server, list its tools
  POST /mcp-connections/call             — call a tool on an external MCP server

Registry CRUD endpoints (new):
  GET    /mcp-connections/registry                  — list DB-persisted servers
  POST   /mcp-connections/registry                  — add a new server
  PATCH  /mcp-connections/registry/{id}             — update a server
  DELETE /mcp-connections/registry/{id}             — remove a server
  POST   /mcp-connections/registry/{id}/discover    — cache tools from server
  POST   /mcp-connections/registry/{id}/health      — ping + update health status

Capability routing:
  POST   /mcp-connections/capability                — call a business capability
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from auth import PermissionChecker, get_current_user
from database import get_session
from models.mcp_server import MCPServerCreate, MCPServerRead, MCPServerUpdate, MCPToolCacheRead
from models.models import User
from services.mcp import capability_router as cap_router
from services.mcp import connection_service, registry_service
from mcp_tools.tool_catalog import invalidate_connections_cache as _invalidate_tool_cache
from services.platform.mcp_client import (
    EXTERNAL_MCP_SERVERS,
    call_external_tool,
    list_external_tools,
    ping_server,
)

router = APIRouter(prefix="/mcp-connections", tags=["MCP Connections"])


# ── Static proxy endpoints (existing) ─────────────────────────────────────────── #

@router.get("/servers")
async def list_static_servers(current_user: User = Depends(get_current_user)):
    """Return all hardcoded external MCP servers with live status."""
    statuses = []
    for prefix in EXTERNAL_MCP_SERVERS:
        status = await ping_server(prefix)
        statuses.append(status)
    return {"servers": statuses}


@router.get("/servers/{prefix}")
async def inspect_static_server(
    prefix: str,
    current_user: User = Depends(get_current_user),
):
    """Ping a hardcoded server and list all tools it exposes."""
    if prefix not in EXTERNAL_MCP_SERVERS:
        raise HTTPException(status_code=404, detail=f"No server registered for '{prefix}'")
    status = await ping_server(prefix)
    tools = await list_external_tools(prefix)
    return {**status, "tools": tools}


class MCPToolCallRequest(BaseModel):
    server: str
    tool: str
    arguments: dict[str, Any] = {}
    auth_token: str | None = None


@router.post("/call")
async def call_mcp_tool(
    req: MCPToolCallRequest,
    current_user: User = Depends(get_current_user),
):
    """Proxy a tool call to a hardcoded external MCP server."""
    if req.server not in EXTERNAL_MCP_SERVERS:
        raise HTTPException(status_code=404, detail=f"No server registered for '{req.server}'")
    result = await call_external_tool(
        prefix=req.server,
        tool_name=req.tool,
        arguments=req.arguments,
        auth_token=req.auth_token,
    )
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


# ── Registry CRUD ─────────────────────────────────────────────────────────────── #

@router.get("/registry", response_model=list[MCPServerRead])
def list_registry(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List all DB-persisted MCP servers for the current company."""
    return registry_service.list_servers(session, current_user.company_id)


@router.post("/registry", response_model=MCPServerRead)
def create_registry_server(
    data: MCPServerCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Add a new MCP server to the company's registry."""
    server = registry_service.create_server(session, current_user.company_id, data)
    _invalidate_tool_cache(current_user.company_id)
    return server


@router.patch("/registry/{server_id}", response_model=MCPServerRead)
def update_registry_server(
    server_id: int,
    data: MCPServerUpdate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    server = registry_service.update_server(session, current_user.company_id, server_id, data)
    _invalidate_tool_cache(current_user.company_id)
    return server


@router.delete("/registry/{server_id}")
def delete_registry_server(
    server_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    registry_service.delete_server(session, current_user.company_id, server_id)
    _invalidate_tool_cache(current_user.company_id)
    return {"deleted": True}


@router.post("/registry/{server_id}/discover")
async def discover_server_tools(
    server_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Connect to the server, fetch its tool list, and cache it in mcp_tool_cache."""
    server = registry_service.get_server(session, current_user.company_id, server_id)
    from services.mcp.capability_router import _resolve_token
    token = _resolve_token(session, current_user.company_id, server.provider)
    count = await connection_service.discover_and_cache_tools(session, server, token)
    tools = registry_service.get_tool_cache(session, server_id)
    return {"server": server.name, "tools_cached": count, "tools": [t.tool_name for t in tools]}


@router.post("/registry/{server_id}/health")
async def ping_registry_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Ping a registry server and update its health status."""
    server = registry_service.get_server(session, current_user.company_id, server_id)
    from services.mcp.capability_router import _resolve_token
    token = _resolve_token(session, current_user.company_id, server.provider)
    client = connection_service.connect_server(server, token)
    try:
        tools = await client.list_tools()
        registry_service.mark_health(session, server_id, "healthy")
        return {"server": server.name, "status": "healthy", "tool_count": len(tools)}
    except Exception as exc:
        registry_service.mark_health(session, server_id, "unhealthy")
        return {"server": server.name, "status": "unhealthy", "error": str(exc)}
    finally:
        if hasattr(client, "close"):
            await client.close()


# ── Capability routing ────────────────────────────────────────────────────────── #

class CapabilityRequest(BaseModel):
    capability: str
    arguments: dict[str, Any] = {}


@router.post("/capability")
async def route_capability(
    req: CapabilityRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Route a business capability to the best available MCP server tool."""
    return await cap_router.route_capability(
        session=session,
        company_id=current_user.company_id,
        capability=req.capability,
        arguments=req.arguments,
        user_id=current_user.id,
    )


@router.get("/capabilities")
def list_capabilities(current_user: User = Depends(get_current_user)):
    """List all available business capability names."""
    return {"capabilities": cap_router.get_capabilities()}
