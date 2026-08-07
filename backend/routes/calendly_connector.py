from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from models.mcp_server import MCPServer, MCPServerCreate
from services.mcp import registry_service
from services.mcp.connection_service import connect_server, discover_and_cache_tools
from mcp_tools.tool_catalog import invalidate_connections_cache as _invalidate_tool_cache
from services.mcp.dcr_client import (
    build_auth_url,
    exchange_code,
    generate_pkce,
    refresh_access_token,
    register_client,
)
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/calendly", tags=["Calendly"])

_PROVIDER   = "calendly"
_MCP_URL    = "https://mcp.calendly.com/mcp"
_MCP_BASE   = "https://mcp.calendly.com"


# ── Auth server metadata (static — discovered once and cached here) ───────────

_AUTH_SERVER = {
    "authorization_endpoint": "https://calendly.com/oauth/authorize",
    "token_endpoint":          "https://calendly.com/oauth/token",
    "registration_endpoint":   "https://calendly.com/oauth/register",
}


# ── Credential storage helpers ────────────────────────────────────────────────

def _save(session: Session, company_id: int, key_name: str, value: str) -> None:
    enc = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == key_name,
        )
    ).first()
    if existing:
        existing.value_encrypted = enc
        existing.is_active = True
        existing.updated_at = utc_now()
        session.add(existing)
    else:
        session.add(ProviderCredential(
            company_id=company_id,
            provider=_PROVIDER,
            key_name=key_name,
            value_encrypted=enc,
            is_active=True,
        ))
    session.commit()


def _get(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == key_name,
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception:
        return None


def _delete_all(session: Session, company_id: int) -> None:
    for cred in session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_calendly_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Calendly access token (used by capability router)."""
    return _get(session, company_id, "access_token")


# ── MCP server row ────────────────────────────────────────────────────────────

def _upsert_mcp_server(session: Session, company_id: int) -> MCPServer:
    existing = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.provider == _PROVIDER,
        )
    ).first()
    if existing:
        existing.enabled = True
        existing.url = _MCP_URL
        existing.transport = "http"
        existing.auth_type = "oauth2"
        existing.updated_at = utc_now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        _invalidate_tool_cache(company_id)
        return existing

    server = registry_service.create_server(
        session,
        company_id,
        MCPServerCreate(
            name="calendly",
            provider=_PROVIDER,
            url=_MCP_URL,
            transport="http",
            auth_type="oauth2",
            config_json={},
            capabilities_json=[
                "schedule_meeting",
                "get_availability",
                "list_bookings",
                "reschedule_meeting",
                "cancel_meeting",
            ],
            priority=80,
        ),
    )
    _invalidate_tool_cache(company_id)
    return server


def _delete_mcp_server(session: Session, company_id: int) -> None:
    server = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.provider == _PROVIDER,
        )
    ).first()
    if server:
        registry_service.delete_server(session, company_id, server.id)
        _invalidate_tool_cache(company_id)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """
    Step 1: DCR (if needed) + build PKCE auth URL.
    Returns {auth_url} for the frontend to open as a popup.
    """
    redirect_uri = _redirect_uri(request)

    # DCR: get or register client_id for this company
    client_id = _get(session, current_user.company_id, "dcr_client_id")
    if not client_id:
        try:
            reg = await register_client(
                registration_endpoint=_AUTH_SERVER["registration_endpoint"],
                client_name="Rio CRM",
                redirect_uris=[redirect_uri],
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"DCR registration failed: {exc}")
        client_id = reg.get("client_id")
        if not client_id:
            raise HTTPException(status_code=502, detail=f"No client_id in DCR response: {reg}")
        _save(session, current_user.company_id, "dcr_client_id", client_id)
        logger.info("[calendly] DCR registered client_id for company %s", current_user.company_id)

    # PKCE
    verifier, challenge = generate_pkce()
    state = f"{current_user.company_id}:{secrets.token_urlsafe(16)}"

    # Store state + verifier for the callback
    _save(session, current_user.company_id, "pending_oauth", json.dumps({
        "state": state,
        "verifier": verifier,
    }))

    auth_url = build_auth_url(
        authorization_endpoint=_AUTH_SERVER["authorization_endpoint"],
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
    )
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/callback")
async def calendly_callback(
    request: Request,
    session: Session = Depends(get_session),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Step 2: Calendly redirects here after user approves.
    Exchanges code for tokens, stores them, then redirects to the settings UI.
    """
    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")

    if error:
        logger.warning("[calendly] OAuth error from Calendly: %s", error)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&calendly=error")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Parse company_id from state
    try:
        company_id = int(state.split(":")[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Load and verify pending OAuth
    pending_raw = _get(session, company_id, "pending_oauth")
    if not pending_raw:
        raise HTTPException(status_code=400, detail="No pending OAuth session — try connecting again")
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Corrupted OAuth session")

    if pending.get("state") != state:
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF")

    code_verifier = pending["verifier"]
    redirect_uri  = _redirect_uri(request)
    client_id     = _get(session, company_id, "dcr_client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="No DCR client_id — try connecting again")

    # Exchange code for tokens
    try:
        tokens = await exchange_code(
            token_endpoint=_AUTH_SERVER["token_endpoint"],
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("[calendly] Token exchange failed: %s", exc.response.text)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&calendly=error")
    except Exception as exc:
        logger.error("[calendly] Token exchange error: %s", exc)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&calendly=error")

    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        logger.error("[calendly] No access_token in response: %s", tokens)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&calendly=error")

    # Persist tokens; clean up pending state
    _save(session, company_id, "access_token", access_token)
    if refresh_token:
        _save(session, company_id, "refresh_token", refresh_token)

    # Remove pending_oauth entry
    for cred in session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == "pending_oauth",
        )
    ).all():
        session.delete(cred)
    session.commit()

    # Register + discover MCP server tools
    server = _upsert_mcp_server(session, company_id)
    try:
        await discover_and_cache_tools(session, server, access_token)
    except Exception as exc:
        logger.warning("[calendly] Tool discovery failed (non-fatal): %s", exc)

    logger.info("[calendly] Company %s connected via OAuth", company_id)
    return RedirectResponse(
        url=f"{frontend_base}/settings?section=mcp_connections&calendly=connected"
    )


@router.get("/status")
async def status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get(session, current_user.company_id, "access_token")
    if not token:
        return {"connected": False, "mcp_url": _MCP_URL}

    server = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == current_user.company_id,
            MCPServer.provider == _PROVIDER,
        )
    ).first()
    if not server:
        return {"connected": False, "mcp_url": _MCP_URL, "error": "MCP server not registered"}

    client = connect_server(server, token)
    try:
        tools = await client.list_tools()
        return {
            "connected": True,
            "mcp_url": _MCP_URL,
            "tool_count": len(tools),
            "last_health_status": server.last_health_status,
        }
    except Exception as exc:
        return {
            "connected": False,
            "mcp_url": _MCP_URL,
            "last_health_status": "unhealthy",
            "error": str(exc),
        }
    finally:
        if hasattr(client, "close"):
            await client.close()


@router.delete("/disconnect")
def disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_all(session, current_user.company_id)
    _delete_mcp_server(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Exchange stored refresh token for a new access token."""
    rt = _get(session, current_user.company_id, "refresh_token")
    if not rt:
        raise HTTPException(status_code=400, detail="No refresh token — reconnect Calendly")
    client_id = _get(session, current_user.company_id, "dcr_client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="No DCR client_id — reconnect Calendly")
    try:
        tokens = await refresh_access_token(
            token_endpoint=_AUTH_SERVER["token_endpoint"],
            refresh_token=rt,
            client_id=client_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = tokens.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — reconnect Calendly")

    _save(session, current_user.company_id, "access_token", new_token)
    if tokens.get("refresh_token"):
        _save(session, current_user.company_id, "refresh_token", tokens["refresh_token"])
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "CALENDLY_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/calendly/callback",
    )
