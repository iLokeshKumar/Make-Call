"""
hubspot_oauth.py - HubSpot OAuth 2.0 flow for Rio CRM.

Setup (one-time):
  1. Go to https://developers.hubspot.com/ → Create App
  2. Under Auth, set redirect URI to: {BACKEND_URL}/crm/hubspot/callback
  3. Add scopes: crm.objects.contacts.read/write, crm.objects.deals.read/write,
                 crm.objects.companies.read/write, crm.schemas.contacts.read
  4. Add to .env:
       HUBSPOT_CLIENT_ID=...
       HUBSPOT_CLIENT_SECRET=...
       HUBSPOT_REDIRECT_URI=http://localhost:6060/crm/hubspot/callback

Flow:
  GET    /crm/hubspot/auth-url   -> returns HubSpot OAuth URL for browser redirect
  GET    /crm/hubspot/callback   -> receives code, exchanges for tokens, stores them
  GET    /crm/hubspot/status     -> check connection status
  DELETE /crm/hubspot/disconnect -> remove stored tokens
  POST   /crm/hubspot/refresh    -> exchange refresh token for new access token
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
from models.models import ProviderCredential, User, utc_now
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/hubspot", tags=["HubSpot OAuth"])

HUBSPOT_AUTH_URL  = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_MCP_URL   = "https://mcp.hubspot.com/"

HUBSPOT_SCOPES = " ".join([
    "crm.objects.contacts.read",
    "crm.objects.companies.read",
    "crm.objects.deals.read",
    "crm.objects.owners.read",
    "crm.schemas.contacts.read",
    "crm.schemas.companies.read",
    "crm.schemas.deals.read",
])


# ── Token storage helpers (ProviderCredential pattern) ────────────────────── #

def _save_token(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "hubspot",
            ProviderCredential.key_name == key_name,
        )
    ).first()
    if existing:
        existing.value_encrypted = encrypted
        existing.is_active = True
        existing.updated_at = utc_now()
        session.add(existing)
    else:
        session.add(ProviderCredential(
            company_id=company_id,
            provider="hubspot",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get_token(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "hubspot",
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


def _delete_tokens(session: Session, company_id: int) -> None:
    for cred in session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "hubspot",
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_hubspot_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored HubSpot access token (used by HubSpot provider adapter)."""
    return _get_token(session, company_id, "access_token")


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Return the HubSpot OAuth URL. Redirect the user's browser there to authorize."""
    client_id = os.getenv("HUBSPOT_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="HUBSPOT_CLIENT_ID not set. Create an app at https://developers.hubspot.com/",
        )
    redirect_uri = _redirect_uri(request)
    params = (
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={HUBSPOT_SCOPES.replace(' ', '%20')}"
        f"&state={current_user.company_id}"
    )
    return {"auth_url": HUBSPOT_AUTH_URL + params, "redirect_uri": redirect_uri}


@router.get("/callback")
async def hubspot_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """HubSpot redirects here after user authorizes. Exchanges code for tokens."""
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("HUBSPOT_CLIENT_ID")
    client_secret = os.getenv("HUBSPOT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="HUBSPOT_CLIENT_ID / HUBSPOT_CLIENT_SECRET not configured")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                HUBSPOT_TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  _redirect_uri(request),
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
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
        raise HTTPException(status_code=400, detail=f"No access_token in HubSpot response: {data}")

    _save_token(session, company_id, "access_token", access_token)
    if refresh_token:
        _save_token(session, company_id, "refresh_token", refresh_token)

    logger.info("[hubspot_oauth] Company %s connected to HubSpot", company_id)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?hubspot=connected")


@router.get("/status")
def hubspot_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get_token(session, current_user.company_id, "access_token")
    return {
        "connected": bool(token),
        "mcp_url": HUBSPOT_MCP_URL,
        "scopes": HUBSPOT_SCOPES.split(),
    }


@router.delete("/disconnect")
def hubspot_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_tokens(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def hubspot_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Exchange a stored refresh token for a new access token."""
    refresh_token = _get_token(session, current_user.company_id, "refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect HubSpot.")

    client_id     = os.getenv("HUBSPOT_CLIENT_ID")
    client_secret = os.getenv("HUBSPOT_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                HUBSPOT_TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = data.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect HubSpot.")

    _save_token(session, current_user.company_id, "access_token", new_token)
    if new_rt := data.get("refresh_token"):
        _save_token(session, current_user.company_id, "refresh_token", new_rt)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "HUBSPOT_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/hubspot/callback",
    )
