"""
instantly_oauth.py - Instantly.ai API key connector for Rio CRM.

Instantly uses API key auth (not OAuth). The user pastes their key from
Instantly Settings → API Keys. We validate it against the Instantly API
then store it in ProviderCredential.

Setup (one-time):
  Log in to app.instantly.ai → Settings → API Keys → Create Key

Endpoints:
  POST   /crm/instantly/connect    -> validate + store API key
  GET    /crm/instantly/status     -> check connection (key present + valid)
  DELETE /crm/instantly/disconnect -> remove stored key
"""
from __future__ import annotations

import logging
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
router = APIRouter(prefix="/crm/instantly", tags=["Instantly"])

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"


# ── Token storage helpers ─────────────────────────────────────────────────── #

def _save(session: Session, company_id: int, key_name: str, value: str) -> None:
    encrypted = encrypt_value(value)
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "instantly",
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
            provider="instantly",
            key_name=key_name,
            value_encrypted=encrypted,
            is_active=True,
        ))
    session.commit()


def _get(session: Session, company_id: int, key_name: str) -> Optional[str]:
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "instantly",
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
            ProviderCredential.provider == "instantly",
        )
    ).all():
        session.delete(cred)
    session.commit()


def get_company_instantly_key(session: Session, company_id: int) -> Optional[str]:
    """Return stored Instantly API key (used by Instantly provider adapter)."""
    return _get(session, company_id, "api_key")


# ── Routes ────────────────────────────────────────────────────────────────── #

class ConnectRequest(BaseModel):
    api_key: str


@router.post("/connect")
async def instantly_connect(
    body: ConnectRequest,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Validate the API key against Instantly, then store it."""
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    # Validate key by listing accounts (lightweight call)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{INSTANTLY_API_BASE}/accounts",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"limit": 1},
            )
        if resp.status_code == 401:
            raise HTTPException(status_code=400, detail="Invalid API key — check Instantly Settings → API Keys.")
        if resp.status_code not in (200, 204):
            raise HTTPException(status_code=400, detail=f"Instantly API returned {resp.status_code}. Verify your key.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not reach Instantly API: {exc}")

    _save(session, current_user.company_id, "api_key", api_key)
    logger.info("[instantly] Company %s connected to Instantly", current_user.company_id)
    return {"connected": True}


@router.get("/status")
def instantly_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    key = _get(session, current_user.company_id, "api_key")
    return {
        "connected": bool(key),
        "auth_type": "api_key",
    }


@router.delete("/disconnect")
def instantly_disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_all(session, current_user.company_id)
    return {"disconnected": True}
