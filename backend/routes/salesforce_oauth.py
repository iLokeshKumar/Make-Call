"""
salesforce_oauth.py - Salesforce OAuth 2.0 flow for Rio CRM.

Setup (one-time):
  1. Go to Setup → App Manager → New Connected App in your Salesforce org
  2. Enable OAuth, set callback URL to: {BACKEND_URL}/crm/salesforce/callback
  3. Add scopes: api, refresh_token, offline_access
  4. Add to .env:
       SALESFORCE_CLIENT_ID=<Consumer Key>
       SALESFORCE_CLIENT_SECRET=<Consumer Secret>
       SALESFORCE_REDIRECT_URI=http://localhost:6060/crm/salesforce/callback

Flow:
  GET    /crm/salesforce/auth-url   -> returns Salesforce OAuth URL
  GET    /crm/salesforce/callback   -> receives code, exchanges for tokens + instance_url
  GET    /crm/salesforce/status     -> check connection status
  DELETE /crm/salesforce/disconnect -> remove stored tokens
  POST   /crm/salesforce/refresh    -> exchange refresh token for new access token
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
router = APIRouter(prefix="/crm/salesforce", tags=["Salesforce OAuth"])

SF_AUTH_URL  = "https://login.salesforce.com/services/oauth2/authorize"
SF_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"

SALESFORCE_SCOPES = "api refresh_token offline_access"


# ── Token storage helpers ─────────────────────────────────────────────────── #

def _save_token(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "salesforce",
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
            provider="salesforce",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get_token(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "salesforce",
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
            ProviderCredential.provider == "salesforce",
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_salesforce_token(session: Session, company_id: int) -> tuple[Optional[str], Optional[str]]:
    """Return (access_token, instance_url) for the company (used by SF provider adapter)."""
    return (
        _get_token(session, company_id, "access_token"),
        _get_token(session, company_id, "instance_url"),
    )


# ── Routes ────────────────────────────────────────────────────────────────── #

@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    client_id = os.getenv("SALESFORCE_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="SALESFORCE_CLIENT_ID not set. Create a Connected App in Salesforce Setup → App Manager.",
        )
    redirect_uri = _redirect_uri(request)
    params = (
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SALESFORCE_SCOPES.replace(' ', '%20')}"
        f"&state={current_user.company_id}"
    )
    return {"auth_url": SF_AUTH_URL + params, "redirect_uri": redirect_uri}


@router.get("/callback")
async def salesforce_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    client_id     = os.getenv("SALESFORCE_CLIENT_ID")
    client_secret = os.getenv("SALESFORCE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="SALESFORCE_CLIENT_ID / SALESFORCE_CLIENT_SECRET not configured")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                SF_TOKEN_URL,
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
    instance_url  = data.get("instance_url")  # e.g. https://yourorg.salesforce.com

    if not access_token:
        raise HTTPException(status_code=400, detail=f"No access_token in Salesforce response: {data}")

    _save_token(session, company_id, "access_token", access_token)
    if refresh_token:
        _save_token(session, company_id, "refresh_token", refresh_token)
    if instance_url:
        _save_token(session, company_id, "instance_url", instance_url)

    logger.info("[salesforce_oauth] Company %s connected to Salesforce (instance: %s)", company_id, instance_url)

    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    return RedirectResponse(url=f"{frontend_base}/settings?salesforce=connected")


@router.get("/status")
def salesforce_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token        = _get_token(session, current_user.company_id, "access_token")
    instance_url = _get_token(session, current_user.company_id, "instance_url")
    return {
        "connected":    bool(token),
        "instance_url": instance_url,
        "scopes":       SALESFORCE_SCOPES.split(),
    }


@router.delete("/disconnect")
def salesforce_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_tokens(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/refresh")
async def salesforce_refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    refresh_token = _get_token(session, current_user.company_id, "refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token stored. Re-connect Salesforce.")

    client_id     = os.getenv("SALESFORCE_CLIENT_ID")
    client_secret = os.getenv("SALESFORCE_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                SF_TOKEN_URL,
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
        raise HTTPException(status_code=400, detail="Refresh failed — re-connect Salesforce.")

    _save_token(session, current_user.company_id, "access_token", new_token)
    if new_instance := data.get("instance_url"):
        _save_token(session, current_user.company_id, "instance_url", new_instance)
    return {"refreshed": True}


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _redirect_uri(request: Request) -> str:
    return os.getenv(
        "SALESFORCE_REDIRECT_URI",
        str(request.base_url).rstrip("/") + "/crm/salesforce/callback",
    )
