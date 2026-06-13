"""Google Calendar OAuth per-company + booking status endpoints."""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import CompanySetting, User, utc_now
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/calendar", tags=["Calendar"])

# In-memory PKCE code verifier cache keyed by company_id
_CALENDAR_PKCE_CACHE: dict[int, str] = {}

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

_TOKEN_KEYS = {
    "GCAL_ACCESS_TOKEN",
    "GCAL_REFRESH_TOKEN",
    "GCAL_TOKEN_EXPIRY",
    "GCAL_EMAIL",
}


def _save_setting(session: Session, company_id: int, key: str, value: str, is_secret: bool = True) -> None:
    from utils.encryption import encrypt_value as _enc
    stored = _enc(value) if is_secret else value
    existing = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if existing:
        existing.value = stored
        existing.is_secret = is_secret
        existing.updated_at = utc_now()
        session.add(existing)
    else:
        session.add(CompanySetting(company_id=company_id, key=key, value=stored, is_secret=is_secret))
    session.commit()


def _get_setting(session: Session, company_id: int, key: str) -> Optional[str]:
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not row:
        return None
    return decrypt_value(row.value) if row.is_secret else row.value


def _build_flow(redirect_uri: str):
    """Build a Google OAuth flow from env vars (no credentials file needed)."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise HTTPException(status_code=500, detail="google-auth-oauthlib not installed")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=CALENDAR_SCOPES, redirect_uri=redirect_uri)
    return flow


@router.get("/auth-url")
def get_auth_url(
    request: Request,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Return Google OAuth URL for company-level calendar authorization."""
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", str(request.base_url).rstrip("/") + "/crm/calendar/callback")
    flow = _build_flow(redirect_uri)
    # Embed company_id in state so callback can look up the right company
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        state=str(current_user.company_id),
    )
    # Store PKCE code verifier so the callback can use it
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        _CALENDAR_PKCE_CACHE[current_user.company_id] = code_verifier
    return {"auth_url": auth_url}


@router.get("/callback")
def calendar_oauth_callback(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle Google OAuth callback, store tokens per company."""
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", str(request.base_url).rstrip("/") + "/crm/calendar/callback")
    try:
        company_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    flow = _build_flow(redirect_uri)
    code_verifier = _CALENDAR_PKCE_CACHE.pop(company_id, None)
    try:
        if code_verifier:
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    creds = flow.credentials
    _save_setting(session, company_id, "GCAL_ACCESS_TOKEN", creds.token, is_secret=True)
    if creds.refresh_token:
        _save_setting(session, company_id, "GCAL_REFRESH_TOKEN", creds.refresh_token, is_secret=True)
    if creds.expiry:
        _save_setting(session, company_id, "GCAL_TOKEN_EXPIRY", creds.expiry.isoformat(), is_secret=False)

    # Fetch email
    try:
        import requests as _req
        info = _req.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=5,
        ).json()
        email = info.get("email", "")
        if email:
            _save_setting(session, company_id, "GCAL_EMAIL", email, is_secret=False)
    except Exception:
        pass

    # Redirect to frontend settings page after auth
    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3006")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{frontend_base}/settings?calendar=connected")


@router.get("/status")
def calendar_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Return Google Calendar connection status for company."""
    access_token = _get_setting(session, current_user.company_id, "GCAL_ACCESS_TOKEN")
    email = _get_setting(session, current_user.company_id, "GCAL_EMAIL")
    expiry = _get_setting(session, current_user.company_id, "GCAL_TOKEN_EXPIRY")
    connected = bool(access_token)
    return {"connected": connected, "email": email, "token_expiry": expiry}


@router.delete("/disconnect")
def calendar_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Remove stored Google Calendar tokens for company."""
    for key in ("GCAL_ACCESS_TOKEN", "GCAL_REFRESH_TOKEN", "GCAL_TOKEN_EXPIRY", "GCAL_EMAIL"):
        row = session.exec(
            select(CompanySetting).where(
                CompanySetting.company_id == current_user.company_id,
                CompanySetting.key == key,
            )
        ).first()
        if row:
            session.delete(row)
    session.commit()
    return {"status": "disconnected"}


def get_company_calendar_credentials(session: Session, company_id: int):
    """Return refreshed google.oauth2.credentials.Credentials for a company, or None."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
    except ImportError:
        return None

    access_token = _get_setting(session, company_id, "GCAL_ACCESS_TOKEN")
    refresh_token = _get_setting(session, company_id, "GCAL_REFRESH_TOKEN")
    if not access_token:
        return None

    expiry_str = _get_setting(session, company_id, "GCAL_TOKEN_EXPIRY")
    expiry = None
    if expiry_str:
        from datetime import datetime as _dt
        try:
            expiry = _dt.fromisoformat(expiry_str)
        except Exception:
            pass

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=CALENDAR_SCOPES,
    )
    creds.expiry = expiry

    if creds.expired and refresh_token:
        try:
            creds.refresh(GRequest())
            _save_setting(session, company_id, "GCAL_ACCESS_TOKEN", creds.token, is_secret=True)
            if creds.expiry:
                _save_setting(session, company_id, "GCAL_TOKEN_EXPIRY", creds.expiry.isoformat(), is_secret=False)
        except Exception as exc:
            logger.warning("[Calendar] Token refresh failed for company %s: %s", company_id, exc)
            return None

    return creds
