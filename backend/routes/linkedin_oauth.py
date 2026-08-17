"""
linkedin_oauth.py - LinkedIn Sales Navigator OAuth 2.0 flow for Rio CRM.

Setup (one-time):
  1. Go to https://developer.linkedin.com/ → Create App
  2. Under Auth, set redirect URI to: {BACKEND_URL}/crm/linkedin/callback
  3. Request Products: "Sign In with LinkedIn" + "Sales Navigator Application Platform"
  4. Add to .env:
       LINKEDIN_CLIENT_ID=...
       LINKEDIN_CLIENT_SECRET=...
       LINKEDIN_REDIRECT_URI=http://localhost:6060/crm/linkedin/callback

Flow:
  GET    /crm/linkedin/auth-url   -> returns LinkedIn OAuth URL for browser redirect
  GET    /crm/linkedin/callback   -> receives code, exchanges for tokens, stores them
  GET    /crm/linkedin/status     -> check connection status
  DELETE /crm/linkedin/disconnect -> remove stored tokens
  POST   /crm/linkedin/refresh    -> exchange refresh token for new access token
"""
from __future__ import annotations

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
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/linkedin", tags=["LinkedIn OAuth"])

LINKEDIN_AUTH_URL  = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_MCP_URL   = "https://api.linkedin.com/"

LINKEDIN_SCOPES = " ".join([
    "openid",
    "profile",
    "email",
    "r_sales_nav_cte_v2",
    "rw_sales_nav_cte_v2",
    "r_sales_nav_analytics",
])


# ── Token storage helpers ─────────────────────────────────────────────────── #

def _save_token(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "linkedin",
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
            provider="linkedin",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get_token(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "linkedin",
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
            ProviderCredential.provider == "linkedin",
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_linkedin_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored LinkedIn access token (used by LinkedIn provider adapter)."""
    return _get_token(session, company_id, "access_token")


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="LINKEDIN_CLIENT_ID not set. Create an app at https://developer.linkedin.com/",
        )
    redirect_uri = _redirect_uri(request)
    # Encode company_id in state for retrieval in callback
    state = f"{current_user.company_id}:{secrets.token_urlsafe(8)}"
    params = (
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={LINKEDIN_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    return {"auth_url": LINKEDIN_AUTH_URL + params, "redirect_uri": redirect_uri}


@router.get("/callback")
async def linkedin_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        company_id = int(state.split(":")[0])
    except (TypeError, ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET not configured")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
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
        raise HTTPException(status_code=400, detail=f"No access_token in LinkedIn response: {data}")

    _save_token(session, company_id, "access_token", access_token)
    if refresh_token:
        _save_token(session, company_id, "refresh_token", refresh_token)

    logger.info("[linkedin_oauth] Company %s connected to LinkedIn Sales Navigator", company_id)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?linkedin=connected")


@router.get("/status")
def linkedin_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get_token(session, current_user.company_id, "access_token")
    return {
        "connected": bool(token),
        "mcp_url": LINKEDIN_MCP_URL,
        "scopes": LINKEDIN_SCOPES.split(),
    }


@router.delete("/disconnect")
def linkedin_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_tokens(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def linkedin_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    refresh_token = _get_token(session, current_user.company_id, "refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect LinkedIn.")

    client_id     = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
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
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect LinkedIn.")

    _save_token(session, current_user.company_id, "access_token", new_token)
    if new_rt := data.get("refresh_token"):
        _save_token(session, current_user.company_id, "refresh_token", new_rt)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "LINKEDIN_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/linkedin/callback",
    )
