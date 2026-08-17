"""
zoom_oauth.py - Zoom OAuth 2.0 flow for Rio CRM, wiring the Zoom Meetings
MCP server (https://mcp.zoom.us/mcp/meeting/streamable) as a connected registry
server so agents can search meetings, pull meeting assets, and fetch recordings.

Setup (one-time):
  1. Create an app on the Zoom App Marketplace -> Develop -> Build App -> General app.
     (Zoom's remote MCP servers only support MANUAL client registration — no DCR.)
  2. Note the Client ID / Client Secret under Basic Information -> App Credentials.
  3. Under Basic Information -> OAuth Information, add the redirect URI
     (ZOOM_REDIRECT_URI, or <backend>/crm/zoom/callback).
  4. Add scopes matching the Meetings MCP tools:
       meeting:read:search
       meeting:read:assets
       cloud_recording:read:list_user_recordings
       cloud_recording:read:content
  5. Add to .env:
       ZOOM_CLIENT_ID=...
       ZOOM_CLIENT_SECRET=...
       ZOOM_REDIRECT_URI=http://localhost:6060/crm/zoom/callback

Notes on Zoom's current OAuth behavior (verified against Zoom docs):
  - The token endpoint authenticates the client with an HTTP Basic header
    (Authorization: Basic base64(client_id:client_secret)) — client creds in the
    request body are NOT sufficient.
  - Zoom's newer marketplace consent flow (marketplace.zoom.us/v2/authorize)
    may strip the `state` parameter (and `code_challenge`) from the request.
    The callback therefore tolerates a missing state by falling back to the most
    recent pending OAuth session, and retries the token exchange without the
    PKCE verifier if Zoom rejects it (i.e. the challenge never reached Zoom).

Flow:
  GET    /crm/zoom/auth-url   -> OAuth URL for the frontend popup
  GET    /crm/zoom/callback   -> exchange code, store tokens, register MCP server
  GET    /crm/zoom/status     -> connection status + discovered tool count
  DELETE /crm/zoom/disconnect -> remove tokens + MCP server row
  POST   /crm/zoom/refresh    -> refresh access token (also used by connection_service
                                 to auto-refresh on 401)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from urllib.parse import urlencode

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from models.mcp_server import MCPServer, MCPServerCreate
from services.mcp import registry_service
from services.mcp.connection_service import connect_server, discover_and_cache_tools
from services.mcp.provider_adapters.zoom import ZOOM_MEETINGS_MCP_URL
from mcp_tools.tool_catalog import invalidate_connections_cache as _invalidate_tool_cache
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/zoom", tags=["Zoom"])

_PROVIDER       = "zoom"
_AUTH_ENDPOINT  = "https://zoom.us/oauth/authorize"
_TOKEN_ENDPOINT = "https://zoom.us/oauth/token"

# Scopes required by the four Zoom Meetings MCP tools.
#
# IMPORTANT: Zoom validates the authorize request's `scope` parameter against the
# scopes SAVED on the app in the Marketplace portal, and hard-rejects the request
# with "Invalid scope. Edit on web portal" if any requested scope is not configured.
# So we deliberately do NOT send `scope` in the authorize URL (scopes are app-
# configured); these constants are kept for reference/documentation and so the
# README/setup instructions stay accurate. Add all four in the portal under
# Manage app -> Scopes -> Add scopes.
ZOOM_SCOPES = [
    "meeting:read:search",
    "meeting:read:assets",
    "cloud_recording:read:list_user_recordings",
    "cloud_recording:read:content",
]

# Scope required for the REST meeting-creation executor (zoom_create_meeting).
# The Meetings MCP server only exposes read-only tools, so creating meetings goes
# through POST /v2/users/me/meetings which needs meeting:write. Surfaced on the
# status endpoint and Settings UI so users know exactly why it's unavailable.
MEETING_WRITE_SCOPE = "meeting:write"
MEETING_WRITE_HINT = (
    "Meeting creation is unavailable: this Zoom app is missing the 'meeting:write' scope. "
    "Add 'meeting:write' under Manage app -> Scopes in the Zoom Marketplace, then "
    "disconnect and re-connect Zoom."
)

# Live scope check for legacy connections (connected before scopes were stored).
# GET zoom.us/oauth/tokens/info returns the scopes granted to the access token.
_ZOOM_TOKEN_INFO_ENDPOINT = "https://zoom.us/oauth/tokens/info"
_scope_check_cache: dict[int, tuple[float, Optional[set[str]]]] = {}
_SCOPE_CHECK_TTL = 60.0  # seconds — avoid hammering Zoom on every status poll


def _parse_zoom_scopes(raw: Optional[str]) -> set[str]:
    """Parse Zoom's scope field, which is space- and/or comma-separated."""
    if not raw:
        return set()
    return {s.strip() for s in raw.replace(",", " ").split() if s.strip()}


def _stored_zoom_scopes(session: Session, company_id: int) -> Optional[set[str]]:
    """Return the scopes recorded when the token was issued, or None if unknown."""
    raw = _get(session, company_id, "scopes")
    if not raw:
        return None
    return _parse_zoom_scopes(raw)


async def _live_zoom_scopes(company_id: int, token: str) -> Optional[set[str]]:
    """Best-effort live scope check via Zoom's token-info endpoint (TTL-cached).

    Returns None when the check fails or the endpoint is unreachable, so the UI
    never shows a false 'missing scope' warning for legacy connections.
    """
    now = time.monotonic()
    cached = _scope_check_cache.get(company_id)
    if cached and now - cached[0] < _SCOPE_CHECK_TTL:
        return cached[1]
    result: Optional[set[str]] = None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(_ZOOM_TOKEN_INFO_ENDPOINT, params={"access_token": token})
            if resp.status_code == 200:
                scopes = (resp.json() or {}).get("scopes") or []
                result = {str(s).strip() for s in scopes if str(s).strip()}
    except Exception as exc:
        logger.warning("[zoom] live scope check failed for company %s: %s", company_id, exc)
    _scope_check_cache[company_id] = (now, result)
    return result


def _has_meeting_write_scope(scopes: Optional[set[str]]) -> Optional[bool]:
    if scopes is None:
        return None
    return any(s == "meeting:write" or s.startswith("meeting:write:") for s in scopes)


def _meeting_write_status(scopes: Optional[set[str]]) -> tuple[Optional[bool], Optional[str]]:
    """Return (meeting_write_granted, hint). None = unknown (not determinable)."""
    granted = _has_meeting_write_scope(scopes)
    if granted is None:
        return None, None
    return granted, (None if granted else MEETING_WRITE_HINT)


def zoom_meeting_write_granted(session: Session, company_id: int) -> Optional[bool]:
    """Return True/False/None for whether the stored Zoom token has meeting:write.

    True/False when scopes were recorded at connect/refresh time (or persisted by
    the status endpoint's live check). None when unknown (legacy connection) —
    callers fail open (treat unknown as allowed; the runtime executor and the
    Settings hint cover the definitive missing-scope case). Never makes HTTP calls.
    """
    scopes = _stored_zoom_scopes(session, company_id)
    return _has_meeting_write_scope(scopes)


# ── Credential storage helpers (ProviderCredential pattern) ────────────────── #

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


# ── MCP server row ──────────────────────────────────────────────────────────── #

def _upsert_mcp_server(session: Session, company_id: int) -> MCPServer:
    existing = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.provider == _PROVIDER,
        )
    ).first()
    if existing:
        existing.enabled = True
        existing.url = ZOOM_MEETINGS_MCP_URL
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
            name="zoom",
            provider=_PROVIDER,
            url=ZOOM_MEETINGS_MCP_URL,
            transport="http",
            auth_type="oauth2",
            config_json={},
            capabilities_json=[
                "search_meetings",
                "get_meeting_assets",
                "list_meeting_recordings",
                "get_recording_resource",
            ],
            priority=70,
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


# ── OAuth helpers ───────────────────────────────────────────────────────────── #

def _client_credentials() -> tuple[str, str]:
    client_id = os.getenv("ZOOM_CLIENT_ID")
    client_secret = os.getenv("ZOOM_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET not set. Create a General app on the Zoom App Marketplace "
                   "and add both to the backend environment.",
        )
    return client_id, client_secret


def _basic_auth_header() -> str:
    """Zoom authenticates OAuth clients via an HTTP Basic header (client_secret_basic)."""
    client_id, client_secret = _client_credentials()
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange the authorization code for tokens using Zoom's Basic-auth client flow."""
    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _TOKEN_ENDPOINT,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_token(session: Session, company_id: int) -> dict:
    """Exchange the stored Zoom refresh token for a new access token.

    Exported so connection_service can auto-refresh on 401. Raises on failure.
    """
    rt = _get(session, company_id, "refresh_token")
    if not rt:
        raise HTTPException(status_code=400, detail="No refresh token — reconnect Zoom")
    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _TOKEN_ENDPOINT,
            data={"grant_type": "refresh_token", "refresh_token": rt},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "ZOOM_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/zoom/callback",
    )


def _most_recent_pending(session: Session) -> Optional[tuple[int, dict]]:
    """Return (company_id, pending) for the sole pending Zoom OAuth session.

    Used when Zoom's consent flow drops the `state` param on the callback. The
    pending_oauth rows hold only {state, verifier}; to keep tenant binding safe
    we accept the fallback ONLY when exactly one pending row exists — multiple
    concurrent flows are ambiguous and rejected so tokens never land on the
    wrong company.
    """
    rows = list(session.exec(
        select(ProviderCredential).where(
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == "pending_oauth",
            ProviderCredential.is_active == True,
        ).order_by(ProviderCredential.updated_at.desc())
    ).all())
    if not rows:
        return None
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple pending Zoom OAuth sessions — close other tabs/browsers and try again",
        )
    try:
        return rows[0].company_id, json.loads(decrypt_value(rows[0].value_encrypted))
    except Exception:
        return None


# ── Routes ──────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
async def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Step 1: build the OAuth URL for the frontend popup."""
    client_id, _ = _client_credentials()
    redirect_uri = _redirect_uri(request)

    # Confidential client flow (Zoom docs): no PKCE, no scope param. Zoom rejects
    # the request with "Invalid scope. Edit on web portal" when the scope param
    # names scopes not saved on the app, and PKCE (code_challenge) only applies to
    # public/private-PKCE clients the manually-created app does not enable.
    state = f"{current_user.company_id}:{secrets.token_urlsafe(16)}"
    _save(session, current_user.company_id, "pending_oauth", json.dumps({"state": state}))

    # Build the authorize URL manually — Zoom's documented confidential-client
    # format is exactly response_type + client_id + redirect_uri (+ state). The
    # shared dcr_client.build_auth_url helper is NOT usable here: it requires a
    # code_challenge and always emits PKCE params, which Zoom's marketplace
    # consent flow strips (and which don't apply to confidential clients).
    auth_url = _AUTH_ENDPOINT + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/callback")
async def zoom_callback(
    request: Request,
    session: Session = Depends(get_session),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Step 2: Zoom redirects here after the user approves. Stores tokens, then
    registers + discovers the Zoom Meetings MCP server and returns to settings."""
    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")

    if error:
        logger.warning("[zoom] OAuth error from Zoom: %s", error)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")

    if not code:
        logger.warning("[zoom] Callback missing authorization code")
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")

    # Resolve the pending OAuth session. Zoom's marketplace consent flow may not
    # round-trip our `state` — validate strictly when present, otherwise fall back
    # to the sole pending session (rejected when ambiguous). All failure paths
    # redirect with ?zoom=error so the Settings UI shows a toast instead of raw JSON.
    try:
        if state:
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
        else:
            logger.info("[zoom] Callback received no state — resolving pending OAuth session by recency")
            resolved = _most_recent_pending(session)
            if not resolved:
                raise HTTPException(status_code=400, detail="No pending OAuth session — try connecting again")
            company_id, pending = resolved

        tokens = await _exchange_code(
            code=code,
            redirect_uri=_redirect_uri(request),
        )
    except HTTPException as exc:
        logger.warning("[zoom] Callback rejected: %s", exc.detail)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")
    except httpx.HTTPStatusError as exc:
        logger.error("[zoom] Token exchange failed: %s", exc.response.text)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")
    except Exception as exc:
        logger.error("[zoom] Token exchange error: %s", exc)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")

    access_token = tokens.get("access_token")
    refresh_token_value = tokens.get("refresh_token")
    if not access_token:
        logger.error("[zoom] No access_token in response: %s", tokens)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")

    _save(session, company_id, "access_token", access_token)
    if refresh_token_value:
        _save(session, company_id, "refresh_token", refresh_token_value)
    if tokens.get("scope"):
        # Record the scopes granted to this token so /status can report whether
        # meeting creation (meeting:write) is available without a live call.
        _save(session, company_id, "scopes", tokens["scope"])

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

    # Register + discover MCP server tools. Only report "connected" when the
    # server is genuinely reachable and exposes tools — a broken connection must
    # NOT show the green badge in the UI. (discover_and_cache_tools swallows
    # connection errors internally and returns 0 on failure.)
    server = _upsert_mcp_server(session, company_id)
    tool_count = await discover_and_cache_tools(session, server, access_token)
    if tool_count <= 0:
        logger.error("[zoom] No tools discovered for company %s — connection not usable", company_id)
        return RedirectResponse(url=f"{frontend_base}/settings?section=mcp_connections&zoom=error")

    logger.info("[zoom] Company %s connected via OAuth (%d tools)", company_id, tool_count)
    return RedirectResponse(
        url=f"{frontend_base}/settings?section=mcp_connections&zoom=connected"
    )


@router.get("/status")
async def status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get(session, current_user.company_id, "access_token")
    if not token:
        return {"connected": False, "mcp_url": ZOOM_MEETINGS_MCP_URL}

    server = session.exec(
        select(MCPServer).where(
            MCPServer.company_id == current_user.company_id,
            MCPServer.provider == _PROVIDER,
        )
    ).first()
    if not server:
        return {"connected": False, "mcp_url": ZOOM_MEETINGS_MCP_URL, "error": "MCP server not registered"}

    # Determine whether meeting creation (meeting:write) is available: prefer the
    # scopes recorded when the token was issued; fall back to a live check for
    # legacy connections. Never blocks the connected state on a failed check.
    scopes = _stored_zoom_scopes(session, current_user.company_id)
    if scopes is None:
        scopes = await _live_zoom_scopes(current_user.company_id, token)
        if scopes is not None:
            # Persist the live result so the tool catalog's create_meeting gate
            # (which never makes HTTP calls) sees the definitive scope state.
            _save(session, current_user.company_id, "scopes", " ".join(sorted(scopes)))
            from mcp_tools.tool_catalog import invalidate_connections_cache as _inv_conn_cache
            _inv_conn_cache(current_user.company_id)
    meeting_write_granted, meeting_write_hint = _meeting_write_status(scopes)

    client = connect_server(server, token)
    try:
        tools = await client.list_tools()
        return {
            "connected": True,
            "mcp_url": ZOOM_MEETINGS_MCP_URL,
            "tool_count": len(tools),
            "last_health_status": server.last_health_status,
            "meeting_write_granted": meeting_write_granted,
            "meeting_write_hint": meeting_write_hint,
        }
    except Exception as exc:
        return {
            "connected": False,
            "mcp_url": ZOOM_MEETINGS_MCP_URL,
            "last_health_status": "unhealthy",
            "meeting_write_granted": meeting_write_granted,
            "meeting_write_hint": meeting_write_hint,
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
    _scope_check_cache.pop(current_user.company_id, None)
    return {"disconnected": True}


@router.post("/refresh")
async def refresh(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Exchange the stored refresh token for a new access token."""
    try:
        tokens = await refresh_token(session, current_user.company_id)
    except httpx.HTTPStatusError as exc:
        logger.error("[zoom] Token refresh failed: %s", exc.response.text)
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc.response.text}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = tokens.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — reconnect Zoom")

    _save(session, current_user.company_id, "access_token", new_token)
    if tokens.get("refresh_token"):
        _save(session, current_user.company_id, "refresh_token", tokens["refresh_token"])
    if tokens.get("scope"):
        _save(session, current_user.company_id, "scopes", tokens["scope"])
        # Scopes changed → the create_meeting tool gate (zoom_write group) must
        # re-evaluate immediately instead of waiting out the 60s cache TTL.
        _invalidate_tool_cache(current_user.company_id)
    return {"refreshed": True}
