"""
apollo_oauth.py - Apollo MCP OAuth 2.0 flow for Rio CRM.

Setup (one-time):
  1. Go to Apollo Settings > Integrations > API and create an OAuth app
  2. Set redirect URI to: {BACKEND_URL}/crm/apollo/callback
  3. Add to .env:
       APOLLO_CLIENT_ID=...
       APOLLO_CLIENT_SECRET=...
       APOLLO_REDIRECT_URI=http://localhost:6060/crm/apollo/callback

Flow:
  GET  /crm/apollo/auth-url   -> returns Apollo OAuth URL, redirect user there
  GET  /crm/apollo/callback   -> Apollo redirects here, we exchange code for token
  GET  /crm/apollo/status     -> check connection status for current company
  DELETE /crm/apollo/disconnect -> remove stored tokens
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import CompanySetting, User, utc_now
from utils.encryption import decrypt_value, encrypt_value
from mcp_tools.tool_catalog import invalidate_connections_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/apollo", tags=["Apollo OAuth"])

APOLLO_AUTH_URL   = "https://mcp.apollo.io/mcp/oauth_metadata/redirect_to_authorize"
APOLLO_TOKEN_URL  = "https://mcp.apollo.io/api/v1/oauth/token"
APOLLO_MCP_URL    = "https://mcp.apollo.io/mcp"

APOLLO_SCOPES = " ".join([
    "read_user_profile",
    "contacts_search", "contact_read", "contact_write", "contact_update",
    "mixed_people_api_search", "people_match", "people_bulk_match",
    "organizations_enrich", "organizations_bulk_enrich", "mixed_companies_search",
    "account_write", "account_update",
    "emailer_campaigns_search", "emailer_campaigns_create", "emailer_campaigns_update",
    "emailer_campaigns_approve", "emailer_campaigns_add_contact_ids",
    "emailer_campaigns_remove_or_stop_contact_ids",
    "emailer_messages_create", "emailer_messages_send_now",
    "tasks_create", "tasks_list",
    "contacts_bulk_create", "account_bulk_create",
    "api_usage_stats_read",
])

_TOKEN_KEYS = {"APOLLO_ACCESS_TOKEN", "APOLLO_REFRESH_TOKEN"}


# ── DB helpers (same pattern as calendar.py) ──────────────────────────────── #

def _save(session: Session, company_id: int, key: str, value: str, secret: bool = True) -> None:
    stored = encrypt_value(value) if secret else value
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if row:
        row.value = stored
        row.is_secret = secret
        row.updated_at = utc_now()
        session.add(row)
    else:
        session.add(CompanySetting(company_id=company_id, key=key, value=stored, is_secret=secret))
    session.commit()


def _get(session: Session, company_id: int, key: str) -> Optional[str]:
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not row:
        return None
    return decrypt_value(row.value) if key in _TOKEN_KEYS else row.value


def _delete(session: Session, company_id: int, key: str) -> None:
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if row:
        session.delete(row)
    session.commit()


def get_company_apollo_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Apollo access token for a company (used by mcp_client)."""
    return _get(session, company_id, "APOLLO_ACCESS_TOKEN")


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Return the Apollo OAuth URL. Redirect the user's browser there to authorize."""
    client_id = os.getenv("APOLLO_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="APOLLO_CLIENT_ID not set. Register Rio as an OAuth app in Apollo Settings > Integrations > API.",
        )

    redirect_uri = _redirect_uri(request)
    state = str(current_user.company_id)

    params = (
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={APOLLO_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    auth_url = APOLLO_AUTH_URL + params
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/callback")
async def apollo_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Apollo redirects here after user authorizes. Exchanges code for access token."""
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("APOLLO_CLIENT_ID")
    client_secret = os.getenv("APOLLO_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="APOLLO_CLIENT_ID / APOLLO_CLIENT_SECRET not configured")

    redirect_uri = _redirect_uri(request)

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                APOLLO_TOKEN_URL,
                json={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  redirect_uri,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token exchange error: {exc}")

    access_token  = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token:
        raise HTTPException(status_code=400, detail=f"No access_token in Apollo response: {data}")

    _save(session, company_id, "APOLLO_ACCESS_TOKEN",  access_token,  secret=True)
    if refresh_token:
        _save(session, company_id, "APOLLO_REFRESH_TOKEN", refresh_token, secret=True)
    _save(session, company_id, "APOLLO_CONNECTED", "true", secret=False)
    invalidate_connections_cache(company_id)

    logger.info("[apollo_oauth] Company %s connected to Apollo MCP", company_id)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?apollo=connected")


@router.get("/status")
def apollo_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Check if the current company has a valid Apollo MCP connection."""
    connected = _get(session, current_user.company_id, "APOLLO_CONNECTED") == "true"
    token     = _get(session, current_user.company_id, "APOLLO_ACCESS_TOKEN")
    return {
        "connected": connected and bool(token),
        "mcp_url":   APOLLO_MCP_URL,
        "scopes":    APOLLO_SCOPES.split(),
    }


@router.delete("/disconnect")
def apollo_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Remove stored Apollo tokens for this company."""
    for key in ("APOLLO_ACCESS_TOKEN", "APOLLO_REFRESH_TOKEN", "APOLLO_CONNECTED"):
        _delete(session, current_user.company_id, key)
    invalidate_connections_cache(current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def apollo_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Exchange a stored refresh token for a new access token."""
    refresh_token = _get(session, current_user.company_id, "APOLLO_REFRESH_TOKEN")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect Apollo.")

    client_id     = os.getenv("APOLLO_CLIENT_ID")
    client_secret = os.getenv("APOLLO_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                APOLLO_TOKEN_URL,
                json={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = data.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect Apollo.")

    _save(session, current_user.company_id, "APOLLO_ACCESS_TOKEN", new_token, secret=True)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "APOLLO_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/apollo/callback",
    )
