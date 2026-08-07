"""
rocketreach_mcp_connector.py — RocketReach MCP OAuth 2.1 + DCR connector.

RocketReach hosts an MCP server at https://rocketreach.co/mcp using OAuth 2.1
with Dynamic Client Registration (RFC 7591) — same pattern as Cal.com/Calendly.
Auth server endpoints are discovered at runtime via the MCP discovery spec.

Routes:
  GET    /crm/rocketreach-mcp/auth-url    DCR + PKCE auth URL
  GET    /crm/rocketreach-mcp/callback    Code exchange, store tokens
  GET    /crm/rocketreach-mcp/status      Connected?
  DELETE /crm/rocketreach-mcp/disconnect  Purge tokens + MCP server row
  POST   /crm/rocketreach-mcp/refresh     Refresh access token
"""
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
from services.mcp.connection_service import discover_and_cache_tools
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
router = APIRouter(prefix="/crm/rocketreach-mcp", tags=["RocketReach MCP"])

_PROVIDER = "rocketreach_mcp"
_MCP_URL  = "https://mcp.rocketreach.co/mcp"
_MCP_BASE = "https://mcp.rocketreach.co/mcp"


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


def get_company_rocketreach_mcp_token(session: Session, company_id: int) -> Optional[str]:
    return _get(session, company_id, "access_token")


def _clear_discovery_cache(session: Session, company_id: int) -> None:
    """Purge cached auth server metadata and DCR client_id so the next auth-url request re-discovers."""
    for key in ("auth_server_meta", "dcr_client_id"):
        cred = session.exec(
            select(ProviderCredential).where(
                ProviderCredential.company_id == company_id,
                ProviderCredential.provider == _PROVIDER,
                ProviderCredential.key_name == key,
            )
        ).first()
        if cred:
            session.delete(cred)
    session.commit()


# ── Auth server discovery ─────────────────────────────────────────────────────

_DISCOVERY_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ModelContextProtocol/1.0 (Rio-CRM; +https://rio-crm.io)",
}

_MCP_HOST_ROOT = "https://mcp.rocketreach.co"

# Initialize payload to probe the MCP endpoint for a 401 with auth-server hints
_MCP_INIT_PAYLOAD = json.dumps({
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "rio-crm", "version": "1.0"},
    },
}).encode()


async def _try_get_json(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    try:
        r = await client.get(url, headers=_DISCOVERY_HEADERS)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


async def _discover_auth_server_meta(client: httpx.AsyncClient) -> Optional[dict]:
    """
    Multi-strategy discovery for RocketReach MCP auth server.

    Strategy 1: POST to MCP endpoint, get 401, parse WWW-Authenticate for
    resource_metadata URL → fetch resource doc → follow authorization_servers[0]
    → fetch that server's /.well-known/oauth-authorization-server.

    Strategy 2: Try standard well-known paths on the mcp subdomain directly.
    """
    # ── Strategy 1: MCP probe ─────────────────────────────────────────────────
    try:
        r = await client.post(
            _MCP_URL,
            content=_MCP_INIT_PAYLOAD,
            headers={**_DISCOVERY_HEADERS, "Content-Type": "application/json"},
        )
        if r.status_code == 401:
            www_auth = r.headers.get("www-authenticate", "")
            logger.debug("[rocketreach_mcp] 401 WWW-Authenticate: %s", www_auth)
            # Look for resource_metadata="<url>" in the header
            resource_meta_url: Optional[str] = None
            for segment in www_auth.replace(",", "\n").splitlines():
                seg = segment.strip()
                if seg.lower().startswith("resource_metadata="):
                    resource_meta_url = seg.split("=", 1)[1].strip().strip('"\'')
            if resource_meta_url:
                resource_doc = await _try_get_json(client, resource_meta_url)
                if resource_doc:
                    for as_url in resource_doc.get("authorization_servers", []):
                        as_meta = await _try_get_json(
                            client,
                            f"{as_url.rstrip('/')}/.well-known/oauth-authorization-server",
                        )
                        if as_meta and as_meta.get("authorization_endpoint"):
                            logger.info("[rocketreach_mcp] Discovered via MCP 401 probe → %s", as_url)
                            return as_meta
    except Exception as exc:
        logger.debug("[rocketreach_mcp] MCP probe error: %s", exc)

    # ── Strategy 2: well-known on mcp subdomain ───────────────────────────────
    for url in [
        f"{_MCP_HOST_ROOT}/.well-known/oauth-authorization-server",
        f"{_MCP_URL.rstrip('/')}/.well-known/oauth-authorization-server",
        f"{_MCP_HOST_ROOT}/.well-known/oauth-protected-resource",
    ]:
        doc = await _try_get_json(client, url)
        if doc:
            if doc.get("authorization_endpoint"):
                logger.info("[rocketreach_mcp] Found auth server at %s", url)
                return doc
            # protected-resource doc: follow authorization_servers
            for as_url in doc.get("authorization_servers", []):
                as_meta = await _try_get_json(
                    client,
                    f"{as_url.rstrip('/')}/.well-known/oauth-authorization-server",
                )
                if as_meta and as_meta.get("authorization_endpoint"):
                    logger.info("[rocketreach_mcp] Resolved auth server via %s", url)
                    return as_meta

    return None


async def _get_auth_server(session: Session, company_id: int) -> dict:
    """Return auth server metadata, using DB cache or live discovery."""
    cached_raw = _get(session, company_id, "auth_server_meta")
    if cached_raw:
        try:
            return json.loads(cached_raw)
        except json.JSONDecodeError:
            pass

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        meta = await _discover_auth_server_meta(client)

    if not meta:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not discover RocketReach MCP OAuth endpoints. "
                "RocketReach may be temporarily blocking automated discovery requests. "
                "Please try again in a moment."
            ),
        )

    _save(session, company_id, "auth_server_meta", json.dumps(meta))
    return meta


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
            name="rocketreach_mcp",
            provider=_PROVIDER,
            url=_MCP_URL,
            transport="http",
            auth_type="oauth2",
            config_json={},
            capabilities_json=[
                "enrich_prospect",
                "search_prospects",
            ],
            priority=75,
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
    redirect_uri = _redirect_uri(request)

    # Discover auth server endpoints (cached after first call)
    auth_server = await _get_auth_server(session, current_user.company_id)
    registration_endpoint = auth_server.get("registration_endpoint")
    authorization_endpoint = auth_server.get("authorization_endpoint")
    if not registration_endpoint or not authorization_endpoint:
        raise HTTPException(status_code=502, detail="Incomplete auth server metadata from RocketReach")

    # DCR: get or register client_id for this company
    client_id = _get(session, current_user.company_id, "dcr_client_id")
    if not client_id:
        try:
            reg = await register_client(
                registration_endpoint=registration_endpoint,
                client_name="Rio CRM",
                redirect_uris=[redirect_uri],
            )
        except Exception as exc:
            # Bad endpoints cached → clear so next attempt re-discovers
            _clear_discovery_cache(session, current_user.company_id)
            raise HTTPException(status_code=502, detail=f"DCR registration failed: {exc}")
        client_id = reg.get("client_id")
        if not client_id:
            _clear_discovery_cache(session, current_user.company_id)
            raise HTTPException(status_code=502, detail=f"No client_id in DCR response: {reg}")
        _save(session, current_user.company_id, "dcr_client_id", client_id)
        logger.info("[rocketreach_mcp] DCR registered client_id for company %s", current_user.company_id)

    # PKCE + state
    verifier, challenge = generate_pkce()
    state = f"{current_user.company_id}:{secrets.token_urlsafe(16)}"
    _save(session, current_user.company_id, "pending_oauth", json.dumps({
        "state": state,
        "verifier": verifier,
    }))

    auth_url = build_auth_url(
        authorization_endpoint=authorization_endpoint,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
    )
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/callback")
async def rocketreach_mcp_callback(
    request: Request,
    session: Session = Depends(get_session),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")

    if error:
        logger.warning("[rocketreach_mcp] OAuth error: %s", error)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&rocketreach_mcp=error")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    try:
        company_id = int(state.split(":")[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    pending_raw = _get(session, company_id, "pending_oauth")
    if not pending_raw:
        raise HTTPException(status_code=400, detail="No pending OAuth session — try connecting again")
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Corrupted OAuth session")

    if pending.get("state") != state:
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF")

    auth_server = await _get_auth_server(session, company_id)
    token_endpoint = auth_server.get("token_endpoint")
    if not token_endpoint:
        raise HTTPException(status_code=502, detail="No token_endpoint in auth server metadata")

    code_verifier = pending["verifier"]
    redirect_uri  = _redirect_uri(request)
    client_id     = _get(session, company_id, "dcr_client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="No DCR client_id — try connecting again")

    try:
        tokens = await exchange_code(
            token_endpoint=token_endpoint,
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("[rocketreach_mcp] Token exchange failed: %s", exc.response.text)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&rocketreach_mcp=error")
    except Exception as exc:
        logger.error("[rocketreach_mcp] Token exchange error: %s", exc)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&rocketreach_mcp=error")

    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        logger.error("[rocketreach_mcp] No access_token in response: %s", tokens)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&rocketreach_mcp=error")

    _save(session, company_id, "access_token", access_token)
    if refresh_token:
        _save(session, company_id, "refresh_token", refresh_token)

    # Clean up pending_oauth
    for cred in session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == "pending_oauth",
        )
    ).all():
        session.delete(cred)
    session.commit()

    server = _upsert_mcp_server(session, company_id)
    try:
        await discover_and_cache_tools(session, server, access_token)
    except Exception as exc:
        logger.warning("[rocketreach_mcp] Tool discovery failed (non-fatal): %s", exc)

    logger.info("[rocketreach_mcp] Company %s connected via OAuth", company_id)
    return RedirectResponse(
        url=f"{frontend_base}/settings?section=mcp_connections&rocketreach_mcp=connected"
    )


@router.get("/status")
def status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get(session, current_user.company_id, "access_token")
    return {"connected": bool(token), "mcp_url": _MCP_URL}


@router.post("/reset-discovery")
def reset_discovery(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Clear cached auth server metadata and DCR client_id to force re-discovery."""
    _clear_discovery_cache(session, current_user.company_id)
    return {"reset": True}


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
    rt = _get(session, current_user.company_id, "refresh_token")
    if not rt:
        raise HTTPException(status_code=400, detail="No refresh token — reconnect RocketReach")
    client_id = _get(session, current_user.company_id, "dcr_client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="No DCR client_id — reconnect RocketReach")

    auth_server = await _get_auth_server(session, current_user.company_id)
    token_endpoint = auth_server.get("token_endpoint")
    if not token_endpoint:
        raise HTTPException(status_code=502, detail="No token_endpoint in auth server metadata")

    try:
        tokens = await refresh_access_token(
            token_endpoint=token_endpoint,
            refresh_token=rt,
            client_id=client_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = tokens.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — reconnect RocketReach")

    _save(session, current_user.company_id, "access_token", new_token)
    if tokens.get("refresh_token"):
        _save(session, current_user.company_id, "refresh_token", tokens["refresh_token"])
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "ROCKETREACH_MCP_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/rocketreach-mcp/callback",
    )
