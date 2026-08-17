"""
RocketReach connector — API key auth (no OAuth).

RocketReach uses a simple API key passed in the X-Api-Key header.
We store it encrypted in ProviderCredential and expose a status/connect/disconnect
surface that matches the ConnectorCard contract in the frontend.

Setup:
  1. Sign up at https://rocketreach.co → Settings → API
  2. Copy your API key
  3. POST /crm/rocketreach/connect  { "api_key": "..." }

Endpoints:
  POST   /crm/rocketreach/connect     Save API key (validates against RocketReach)
  GET    /crm/rocketreach/status      Check if key is stored and valid
  DELETE /crm/rocketreach/disconnect  Remove key
  POST   /crm/rocketreach/lookup      Lookup a person by name + company (proxy)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/rocketreach", tags=["RocketReach"])

_PROVIDER = "rocketreach"
_KEY_NAME  = "api_key"
_BASE_URL  = "https://api.rocketreach.co/v2"


# ── Storage helpers ──────────────────────────────────────────────────────────

def _save(session: Session, company_id: int, value: str) -> None:
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == _KEY_NAME,
        )
    ).first()
    enc = encrypt_value(value)
    if existing:
        existing.value_encrypted = enc
        existing.is_active = True
        existing.updated_at = utc_now()
        session.add(existing)
    else:
        session.add(ProviderCredential(
            company_id=company_id,
            provider=_PROVIDER,
            key_name=_KEY_NAME,
            value_encrypted=enc,
            is_active=True,
        ))
    session.commit()


def _get(session: Session, company_id: int) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == _KEY_NAME,
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception:
        return None


def _delete(session: Session, company_id: int) -> None:
    for cred in session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_rocketreach_key(session: Session, company_id: int) -> Optional[str]:
    return _get(session, company_id)


# ── Routes ───────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    api_key: str


class LookupRequest(BaseModel):
    name: str
    current_employer: Optional[str] = None
    linkedin_url: Optional[str] = None


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Save and validate a RocketReach API key."""
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key is required")

    # Validate against RocketReach account endpoint
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE_URL}/account",
                headers={"X-Api-Key": key},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach RocketReach: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="Invalid RocketReach API key")
    if not resp.ok:
        raise HTTPException(status_code=400, detail=f"RocketReach validation failed: {resp.status_code}")

    _save(session, current_user.company_id, key)
    logger.info("[rocketreach] Company %s connected", current_user.company_id)

    account = resp.json()
    return {
        "connected": True,
        "name": account.get("name"),
        "email": account.get("email"),
        "plan": account.get("plan", {}).get("name"),
        "lookups_remaining": account.get("lookups_remaining"),
    }


@router.get("/status")
def status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    key = _get(session, current_user.company_id)
    return {"connected": bool(key)}


@router.delete("/disconnect")
def disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete(session, current_user.company_id)
    return {"disconnected": True}


@router.post("/lookup")
async def lookup(
    body: LookupRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Proxy a person lookup to RocketReach. Returns emails + phones."""
    key = _get(session, current_user.company_id)
    if not key:
        raise HTTPException(status_code=400, detail="RocketReach not connected. Add an API key first.")

    payload: dict = {"name": body.name}
    if body.current_employer:
        payload["current_employer"] = body.current_employer
    if body.linkedin_url:
        payload["linkedin_url"] = body.linkedin_url

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BASE_URL}/person/lookup",
                json=payload,
                headers={"X-Api-Key": key, "Content-Type": "application/json"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RocketReach request failed: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="RocketReach API key invalid or expired")
    if not resp.ok:
        detail = resp.json().get("detail", resp.text)
        raise HTTPException(status_code=resp.status_code, detail=f"RocketReach error: {detail}")

    data = resp.json()
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "title": data.get("current_title"),
        "company": data.get("current_employer"),
        "linkedin_url": data.get("linkedin_url"),
        "emails": data.get("emails", []),
        "phones": data.get("phones", []),
        "profile_pic": data.get("profile_pic"),
        "status": data.get("status"),
    }
