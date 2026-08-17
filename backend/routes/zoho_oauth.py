"""
zoho_oauth.py - Zoho CRM OAuth 2.0 flow for Rio CRM.

Setup (one-time):
  1. Go to https://api-console.zoho.com/ and create a Server-Based Application
  2. Set redirect URI to: {BACKEND_URL}/crm/zoho/callback
  3. Add to .env:
       ZOHO_CLIENT_ID=...
       ZOHO_CLIENT_SECRET=...
       ZOHO_REDIRECT_URI=http://localhost:6060/crm/zoho/callback

Flow:
  GET    /crm/zoho/auth-url     -> returns Zoho OAuth URL for browser redirect
  GET    /crm/zoho/callback     -> receives code, exchanges for tokens, stores them
  GET    /crm/zoho/status       -> check connection status
  DELETE /crm/zoho/disconnect   -> remove stored tokens
  POST   /crm/zoho/refresh      -> exchange refresh token for new access token
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from mcp_tools.tool_catalog import invalidate_connections_cache
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/zoho", tags=["Zoho OAuth"])

ZOHO_AUTH_URL  = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_MCP_URL   = "https://mcp.zoho.com/"

ZOHO_SCOPES = " ".join([
    "ZohoCRM.modules.ALL",
    "ZohoCRM.settings.ALL",
    "ZohoCRM.bulk.ALL",
    "ZohoCRM.org.ALL",
    "WorkDrive.files.READ",
    # Zoho requires BOTH WorkDrive scopes for the binary file download API
    # (download.zoho.com) — without ZohoFiles.files.READ it returns 401
    # INVALID_OAUTHSCOPE (confirmed in Zoho's help forum).
    "ZohoFiles.files.READ",
    "ZohoSheet.dataAPI.READ",
    "ZohoBooks.fullaccess.all",
])


# ── Token storage helpers (ProviderCredential pattern) ────────────────────────── #

def _save_token(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "zoho",
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
            provider="zoho",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get_token(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "zoho",
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
            ProviderCredential.provider == "zoho",
        )
    ).all():
        session.delete(cred)
    session.commit()


# Zoho access tokens are short-lived (~1 hour). Refresh the token 5 min before
# it expires so long-running reads (e.g. Zoho Books inventory) never fail with a
# stale-token 401.
_ACCESS_TOKEN_SKEW_SECONDS = 300


def _token_is_expired(token: str) -> bool:
    """Return True when the access token is expired or within the skew window.

    Decodes the JWT without verifying the signature (the token is only used to
    read its ``exp`` claim). Non-JWT/opaque tokens fail open (return False) —
    the 401 retry path in callers covers those stale cases.
    """
    try:
        import jwt as _jwt
        payload = _jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if not exp:
            return False
        return time.time() >= float(exp) - _ACCESS_TOKEN_SKEW_SECONDS
    except Exception:
        return False


def get_or_refresh_zoho_token(session: Session, company_id: int, force: bool = False) -> Optional[str]:
    """Return a fresh Zoho access token, auto-refreshing when needed.

    Reads the stored access token. If it is missing, expired, close to expiry,
    or ``force`` is True (e.g. a 401 came back from Zoho), exchanges the stored
    refresh token at ZOHO_TOKEN_URL, persists the new access token, and returns
    it. Returns None when Zoho is not connected or the refresh fails.
    """
    token = _get_token(session, company_id, "access_token")
    if not token:
        return None
    if not force and not _token_is_expired(token):
        return token

    refresh_token = _get_token(session, company_id, "refresh_token")
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    if not refresh_token or not client_id or not client_secret:
        return None

    try:
        resp = httpx.post(
            ZOHO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[zoho_oauth] Token refresh failed for company %s: %s", company_id, exc)
        return None

    new_token = data.get("access_token")
    if not new_token:
        return None
    _save_token(session, company_id, "access_token", new_token)
    if new_rt := data.get("refresh_token"):
        _save_token(session, company_id, "refresh_token", new_rt)
    invalidate_connections_cache(company_id)
    logger.info("[zoho_oauth] Refreshed Zoho access token for company %s", company_id)
    return new_token


def get_company_zoho_token(session: Session, company_id: int) -> Optional[str]:
    """Return a fresh Zoho access token, auto-refreshing when expired.

    Used by the Zoho provider adapter and REST executors so callers never hit
    a stale-token 401 after ~1 hour.
    """
    return get_or_refresh_zoho_token(session, company_id)


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Return the Zoho OAuth URL. Redirect the user's browser there to authorize."""
    client_id = os.getenv("ZOHO_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="ZOHO_CLIENT_ID not set. Register Rio as an OAuth app at https://api-console.zoho.com/",
        )
    redirect_uri = _redirect_uri(request)
    params = (
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={ZOHO_SCOPES.replace(' ', '%20')}"
        f"&state={current_user.company_id}"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return {"auth_url": ZOHO_AUTH_URL + params, "redirect_uri": redirect_uri}


@router.get("/callback")
async def zoho_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Zoho redirects here after user authorizes. Exchanges code for tokens."""
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET not configured")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                ZOHO_TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  _redirect_uri(request),
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
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
        raise HTTPException(status_code=400, detail=f"No access_token in Zoho response: {data}")

    _save_token(session, company_id, "access_token", access_token)
    if refresh_token:
        _save_token(session, company_id, "refresh_token", refresh_token)
    invalidate_connections_cache(company_id)

    logger.info("[zoho_oauth] Company %s connected to Zoho CRM, Sheet and WorkDrive", company_id)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?zoho=connected")


@router.get("/status")
def zoho_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get_token(session, current_user.company_id, "access_token")
    return {
        "connected": bool(token),
        "mcp_url": ZOHO_MCP_URL,
        "scopes": ZOHO_SCOPES.split(),
    }


@router.delete("/disconnect")
def zoho_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_tokens(session, current_user.company_id)
    invalidate_connections_cache(current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def zoho_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Exchange a stored refresh token for a new access token."""
    refresh_token = _get_token(session, current_user.company_id, "refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect Zoho.")

    client_id     = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                ZOHO_TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = data.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect Zoho.")

    _save_token(session, current_user.company_id, "access_token", new_token)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "ZOHO_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/zoho/callback",
    )
