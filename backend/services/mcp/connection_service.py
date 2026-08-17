"""
connection_service.py - Connects to external MCP servers loaded from the DB registry.

Wraps the existing MCPClient from mcp_client.py with DB-aware auth resolution
and health/tool-cache management via registry_service.
"""
from __future__ import annotations

import logging
import os
import httpx
from typing import Optional

from sqlmodel import Session, select

from models.mcp_server import MCPServer
from services.mcp.registry_service import mark_health, upsert_tool_cache
from services.platform.mcp_client import MCPClient, MCPStdioClient

logger = logging.getLogger(__name__)


def _build_headers(server: MCPServer, token: Optional[str] = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif server.auth_type == "api_key":
        key = server.config_json.get("api_key", "")
        if key:
            header_name = server.config_json.get("header_name", "X-Api-Key")
            headers[header_name] = key
    return headers


def connect_server(server: MCPServer, token: Optional[str] = None) -> MCPClient | MCPStdioClient:
    """Return a client connected to the given server row (HTTP or stdio)."""
    if server.transport == "stdio":
        command = server.config_json.get("command", [])
        api_key_env = server.config_json.get("api_key_env")
        if api_key_env:
            key_value = token or os.environ.get(api_key_env, "")
            extra_env = {api_key_env: key_value} if key_value else {}
        else:
            extra_env = {}
        return MCPStdioClient(command=command, env=extra_env)
    return MCPClient(url=server.url, headers=_build_headers(server, token))


# async def discover_and_cache_tools(
#     session: Session,
#     server: MCPServer,
#     token: Optional[str] = None,
# ) -> int:
#     """Fetch all tools from the server and save them to MCPToolCache. Returns tool count."""
#     client = connect_server(server, token)
#     try:
#         tools = await client.list_tools()
#         upsert_tool_cache(session, server.id, tools)
#         mark_health(session, server.id, "healthy")
#         return len(tools)
#     except Exception as exc:
#         # Provide clearer diagnostics for common HTTP failures from MCP endpoints.
#         try:
#             if isinstance(exc, httpx.HTTPStatusError):
#                 status = exc.response.status_code
#                 if status == 401:
#                     logger.error(
#                         "[connection_service] discover_tools(%s) failed: %s (401 Unauthorized). Check auth token/header for server id=%s url=%s",
#                         server.name, exc, server.id, server.url,
#                     )
#                 elif status == 404:
#                     logger.error(
#                         "[connection_service] discover_tools(%s) failed: %s (404 Not Found). Endpoint may not support MCP; verify URL for server id=%s url=%s",
#                         server.name, exc, server.id, server.url,
#                     )
#                 else:
#                     logger.error(
#                         "[connection_service] discover_tools(%s) failed: %s (status=%s)", server.name, exc, status
#                     )
#             else:
#                 logger.error("[connection_service] discover_tools(%s) failed: %s", server.name, exc)
#         except Exception:
#             logger.error("[connection_service] discover_tools(%s) failed: %s", server.name, exc)
#         mark_health(session, server.id, "unhealthy")
#         return 0
#     finally:
#         if hasattr(client, "close"):
#             await client.close()

async def discover_and_cache_tools(
    session: Session,
    server: MCPServer,
    token: Optional[str] = None,
) -> int:
    """Fetch all tools from the server and save them to MCPToolCache. Returns tool count."""
    client = connect_server(server, token)
    try:
        tools = await client.list_tools()
        upsert_tool_cache(session, server.id, tools)
        mark_health(session, server.id, "healthy")
        return len(tools)
    except Exception as exc:
        # ── Auto-refresh Calendly token on 401 ─────────────────────────────
        refreshed = False
        try:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401:
                if server.provider == "calendly":
                    from routes.calendly_connector import refresh_token as _cal_refresh
                    # We need a request context for refresh_token — call the helper directly
                    from routes.calendly_connector import _get, _save
                    from services.mcp.provider_adapters.calendly import get_token as _get_cal_token
                    rt = _get(session, server.company_id, "refresh_token")
                    if rt:
                        from services.mcp.dcr_client import refresh_access_token
                        client_id = _get(session, server.company_id, "dcr_client_id")
                        if client_id:
                            tokens = await refresh_access_token(
                                token_endpoint="https://calendly.com/oauth/token",
                                refresh_token=rt,
                                client_id=client_id,
                            )
                            new_at = tokens.get("access_token")
                            if new_at:
                                _save(session, server.company_id, "access_token", new_at)
                                if tokens.get("refresh_token"):
                                    _save(session, server.company_id, "refresh_token", tokens["refresh_token"])
                                # Retry with new token
                                client2 = connect_server(server, new_at)
                                tools = await client2.list_tools()
                                upsert_tool_cache(session, server.id, tools)
                                mark_health(session, server.id, "healthy")
                                refreshed = True
                                if hasattr(client2, "close"):
                                    await client2.close()
                elif server.provider == "zoom":
                    from routes.zoom_oauth import _save as _zoom_save
                    from routes.zoom_oauth import refresh_token as _zoom_refresh
                    tokens = await _zoom_refresh(session, server.company_id)
                    new_at = tokens.get("access_token")
                    if new_at:
                        _zoom_save(session, server.company_id, "access_token", new_at)
                        if tokens.get("refresh_token"):
                            _zoom_save(session, server.company_id, "refresh_token", tokens["refresh_token"])
                        client2 = connect_server(server, new_at)
                        tools = await client2.list_tools()
                        upsert_tool_cache(session, server.id, tools)
                        mark_health(session, server.id, "healthy")
                        refreshed = True
                        if hasattr(client2, "close"):
                            await client2.close()
        except Exception as refresh_exc:
            logger.warning("[connection_service] Provider token refresh failed: %s", refresh_exc)
        # ────────────────────────────────────────────────────────────────────
        
        if not refreshed:
            # ... existing error logging unchanged ...
            try:
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code
                    if status == 401:
                        logger.error(
                            "[connection_service] discover_tools(%s) failed: %s (401 Unauthorized). Check auth token/header for server id=%s url=%s",
                            server.name, exc, server.id, server.url,
                        )
                    elif status == 404:
                        logger.error(
                            "[connection_service] discover_tools(%s) failed: %s (404 Not Found). Endpoint may not support MCP; verify URL for server id=%s url=%s",
                            server.name, exc, server.id, server.url,
                        )
                    else:
                        logger.error(
                            "[connection_service] discover_tools(%s) failed: %s (status=%s)", server.name, exc, status
                        )
                else:
                    logger.error("[connection_service] discover_tools(%s) failed: %s", server.name, exc)
            except Exception:
                logger.error("[connection_service] discover_tools(%s) failed: %s", server.name, exc)
            mark_health(session, server.id, "unhealthy")
        return 0
    finally:
        if hasattr(client, "close"):
            await client.close()


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
        client = connect_server(server)
        try:
            await client.list_tools()
            mark_health(session, server.id, "healthy")
            results[server.id] = "healthy"
        except Exception as exc:
            logger.warning("[connection_service] health_check(%s) failed: %s", server.name, exc)
            mark_health(session, server.id, "unhealthy")
            results[server.id] = "unhealthy"
        finally:
            if hasattr(client, "close"):
                await client.close()
    return results


async def refresh_company_servers(company_id: int) -> dict[int, int]:
    """Re-discover + re-cache tools for every enabled server of a company.

    Keeps the capability router's tool caches fresh so _find_server can always
    pick a server that actually exposes the requested tool. Each server uses a
    fresh short-lived DB session so no session is held open across the network
    wait (avoids connection-pool pressure). Returns {server_id: tool_count}.
    """
    from database import engine
    from sqlmodel import Session as _Session

    try:
        with _Session(engine) as session:
            servers = list(session.exec(
                select(MCPServer).where(
                    MCPServer.company_id == company_id,
                    MCPServer.enabled == True,  # noqa: E712
                )
            ).all())
    except Exception as exc:
        logger.warning("[connection_service] refresh: could not list servers for company %s: %s", company_id, exc)
        return {}

    results: dict[int, int] = {}
    for server in servers:
        try:
            with _Session(engine) as session:
                from services.mcp.capability_router import _resolve_token
                token = _resolve_token(session, company_id, server.provider)
                count = await discover_and_cache_tools(session, server, token)
            results[server.id] = count
        except Exception as exc:
            logger.warning(
                "[connection_service] refresh(%s/%s) failed: %s",
                server.name, server.provider, exc,
            )
    return results


async def call_server_tool(
    server: MCPServer,
    tool_name: str,
    arguments: dict,
    token: Optional[str] = None,
) -> dict:
    """Call a tool on the given server and return the result dict."""
    client = connect_server(server, token)
    try:
        result = await client.call_tool(tool_name, arguments)
        return {"result": result, "source": server.name, "provider": server.provider}
    except Exception as exc:
        logger.error(
            "[connection_service] %s/%s failed: %s", server.name, tool_name, exc
        )
        return {"error": str(exc), "source": server.name, "provider": server.provider}
    finally:
        if hasattr(client, "close"):
            await client.close()
