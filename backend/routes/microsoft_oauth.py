"""
microsoft_oauth.py - Microsoft 365 OAuth 2.0 flow for Rio CRM.

Covers: Outlook (email), OneDrive (files), Calendars — one app registration.

Setup (one-time):
  1. Go to https://portal.azure.com/ → Azure Active Directory → App registrations → New registration
  2. Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
  3. Redirect URI (Web): {BACKEND_URL}/crm/microsoft/callback
  4. Under API permissions, add Microsoft Graph delegated scopes:
       Mail.Read, Mail.ReadWrite, Mail.Send,
       Files.Read, Files.ReadWrite,
       Calendars.Read, Calendars.ReadWrite,
       User.Read, offline_access
  5. Under Certificates & secrets → New client secret → copy value
  6. Add to .env:
       MICROSOFT_CLIENT_ID=<Application (client) ID>
       MICROSOFT_CLIENT_SECRET=<Client secret value>
       MICROSOFT_REDIRECT_URI=http://localhost:6060/crm/microsoft/callback

Flow:
  GET    /crm/microsoft/auth-url   -> returns Microsoft OAuth URL
  GET    /crm/microsoft/callback   -> receives code, exchanges for tokens
  GET    /crm/microsoft/status     -> check connection status
  DELETE /crm/microsoft/disconnect -> remove stored tokens
  POST   /crm/microsoft/refresh    -> exchange refresh token for new access token
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/microsoft", tags=["Microsoft 365 OAuth"])

MS_AUTH_URL  = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

MICROSOFT_SCOPES = " ".join([
    "offline_access",
    "User.Read",
    # Outlook email
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    # OneDrive
    "Files.Read",
    "Files.ReadWrite",
    # Calendar
    "Calendars.Read",
    "Calendars.ReadWrite",
])


# ── Token storage helpers ─────────────────────────────────────────────────── #

def _save_token(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "microsoft",
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
            provider="microsoft",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get_token(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "microsoft",
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
            ProviderCredential.provider == "microsoft",
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_microsoft_token(session: Session, company_id: int) -> Optional[str]:
    """Return stored Microsoft access token (used by Microsoft provider adapter)."""
    return _get_token(session, company_id, "access_token")


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    client_id = os.getenv("MICROSOFT_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="MICROSOFT_CLIENT_ID not set. Register an app at https://portal.azure.com/ → App registrations.",
        )
    redirect_uri = _redirect_uri(request)
    params = urlencode({
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  redirect_uri,
        "scope":         MICROSOFT_SCOPES,
        "state":         str(current_user.company_id),
        "response_mode": "query",
        "prompt":        "select_account",
    })
    return {"auth_url": f"{MS_AUTH_URL}?{params}", "redirect_uri": redirect_uri}


@router.get("/callback")
async def microsoft_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("MICROSOFT_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET not configured")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  _redirect_uri(request),
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "scope":         MICROSOFT_SCOPES,
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
        raise HTTPException(status_code=400, detail=f"No access_token in Microsoft response: {data}")

    _save_token(session, company_id, "access_token", access_token)
    if refresh_token:
        _save_token(session, company_id, "refresh_token", refresh_token)

    # Fetch user email for display
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            me = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            email = me.json().get("mail") or me.json().get("userPrincipalName", "")
            if email:
                _save_token(session, company_id, "email", email)
    except Exception:
        pass

    logger.info("[microsoft_oauth] Company %s connected to Microsoft 365", company_id)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?microsoft=connected")


@router.get("/status")
def microsoft_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = _get_token(session, current_user.company_id, "access_token")
    email = _get_token(session, current_user.company_id, "email")
    return {
        "connected": bool(token),
        "email":     email,
        "scopes":    MICROSOFT_SCOPES.split(),
    }


@router.delete("/disconnect")
def microsoft_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_tokens(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def microsoft_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    refresh_token = _get_token(session, current_user.company_id, "refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect Microsoft 365.")

    client_id     = os.getenv("MICROSOFT_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "scope":         MICROSOFT_SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {exc}")

    new_token = data.get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect Microsoft 365.")

    _save_token(session, current_user.company_id, "access_token", new_token)
    if new_rt := data.get("refresh_token"):
        _save_token(session, current_user.company_id, "refresh_token", new_rt)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "MICROSOFT_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/microsoft/callback",
    )
