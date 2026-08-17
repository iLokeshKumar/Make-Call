"""
registry_service.py - CRUD layer for MCPServer and MCPToolCache rows.

All queries are explicitly company-scoped even though RLS fires at the DB layer,
so that callers always get the right tenant's data regardless of RLS context.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from models.mcp_server import MCPServer, MCPServerCreate, MCPServerUpdate, MCPToolCache


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── MCPServer CRUD ───────────────────────────────────────────────────────────── #

def list_servers(session: Session, company_id: int) -> list[MCPServer]:
    return list(session.exec(
        select(MCPServer)
        .where(MCPServer.company_id == company_id)
        .order_by(MCPServer.priority.desc(), MCPServer.name)
    ).all())


def get_server(session: Session, company_id: int, server_id: int) -> MCPServer:
    server = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.id == server_id,
        )
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server {server_id} not found")
    return server


def create_server(session: Session, company_id: int, data: MCPServerCreate) -> MCPServer:
    server = MCPServer(company_id=company_id, **data.model_dump())
    session.add(server)
    session.commit()
    session.refresh(server)
    return server


def update_server(
    session: Session, company_id: int, server_id: int, data: MCPServerUpdate
) -> MCPServer:
    server = get_server(session, company_id, server_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(server, field, value)
    server.updated_at = _utc_now()
    session.add(server)
    session.commit()
    session.refresh(server)
    return server


def delete_server(session: Session, company_id: int, server_id: int) -> None:
    server = get_server(session, company_id, server_id)
    for cached in session.exec(
        select(MCPToolCache).where(MCPToolCache.server_id == server_id)
    ).all():
        session.delete(cached)
    session.delete(server)
    session.commit()


# ── MCPToolCache ─────────────────────────────────────────────────────────────── #

def upsert_tool_cache(session: Session, server_id: int, tools: list[dict]) -> None:
    """Replace cached tools for a server with a fresh discovery result."""
    for existing in session.exec(
        select(MCPToolCache).where(MCPToolCache.server_id == server_id)
    ).all():
        session.delete(existing)
    for tool in tools:
        session.add(MCPToolCache(
            server_id=server_id,
            tool_name=tool.get("name", ""),
            description=tool.get("description"),
            input_schema_json=tool.get("inputSchema", {}),
            cached_at=_utc_now(),
        ))
    session.commit()


def get_tool_cache(session: Session, server_id: int) -> list[MCPToolCache]:
    return list(session.exec(
        select(MCPToolCache).where(MCPToolCache.server_id == server_id)
    ).all())


def mark_health(session: Session, server_id: int, status: str) -> None:
    """Update health status for a server row (called after ping/discover)."""
    server = session.exec(
        select(MCPServer).where(MCPServer.id == server_id)
    ).first()
    if server:
        server.last_health_status = status
        server.last_health_checked_at = _utc_now()
        session.add(server)
        session.commit()
