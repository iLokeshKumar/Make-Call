"""
Tally Prime connector — local gateway bridge (not OAuth).

Tally Prime exposes an HTTP XML interface on localhost:9000 by default.
This connector stores the gateway URL (and optional company name) so the
F3 books-sync agent can post vouchers without hardcoding the address.

No cloud OAuth — Tally runs on-premises. The user pastes the gateway URL
(e.g. http://10.0.0.5:9000) and we do a lightweight ping to verify it's live.

Setup:
  1. Open Tally Prime → Gateway of Tally → Enable (default port 9000)
  2. Note the machine's LAN IP or use localhost if running on same machine
  3. POST /crm/tally/connect  { "gateway_url": "http://localhost:9000", "company_name": "My Firm" }

Endpoints:
  POST   /crm/tally/connect      Save gateway URL + verify ping
  GET    /crm/tally/status       Is the gateway reachable?
  DELETE /crm/tally/disconnect   Remove config
  GET    /crm/tally/companies    List Tally companies (via XML API)
"""
from __future__ import annotations

import logging
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderCredential, User, utc_now
from utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm/tally", tags=["Tally"])

_PROVIDER = "tally"

# Tally XML ping — requests list of companies
_PING_XML = """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>List of Companies</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="List of Companies" ISMODIFY="No">
            <TYPE>Company</TYPE>
            <FETCH>Name</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


# ── Storage helpers ──────────────────────────────────────────────────────────

def _save(session: Session, company_id: int, key_name: str, value: str) -> None:
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == _PROVIDER,
            ProviderCredential.key_name == key_name,
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


def get_tally_gateway_url(session: Session, company_id: int) -> Optional[str]:
    """Used by F3 books-sync agent to resolve the Tally gateway URL."""
    return _get(session, company_id, "gateway_url")


def get_tally_company_name(session: Session, company_id: int) -> Optional[str]:
    return _get(session, company_id, "company_name")


# ── Tally XML helpers ────────────────────────────────────────────────────────

async def _ping_tally(gateway_url: str) -> list[str]:
    """Send a company-list XML request to Tally. Returns list of company names."""
    url = gateway_url.rstrip("/")
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.post(
            url,
            content=_PING_XML.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
        )
    resp.raise_for_status()
    # Parse company names from XML response
    companies: list[str] = []
    try:
        root = ET.fromstring(resp.text)
        for node in root.iter("COMPANY"):
            name = node.findtext("NAME") or node.text
            if name and name.strip():
                companies.append(name.strip())
    except ET.ParseError:
        pass  # Tally returned non-XML (maybe HTML error page)
    return companies


# ── Routes ───────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    gateway_url: str          # e.g. http://localhost:9000
    company_name: Optional[str] = None  # Tally company to use for posting


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Save Tally gateway URL and verify it's reachable."""
    gateway_url = body.gateway_url.strip().rstrip("/")
    if not gateway_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="gateway_url must start with http:// or https://")

    try:
        companies = await _ping_tally(gateway_url)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reach Tally gateway at {gateway_url}. Is Tally Prime running and Gateway of Tally enabled?",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail=f"Tally gateway at {gateway_url} timed out (8s). Check network.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tally gateway error: {exc}")

    _save(session, current_user.company_id, "gateway_url", gateway_url)
    if body.company_name:
        _save(session, current_user.company_id, "company_name", body.company_name)

    logger.info("[tally] Company %s connected gateway %s", current_user.company_id, gateway_url)
    return {
        "connected": True,
        "gateway_url": gateway_url,
        "tally_companies": companies,
        "selected_company": body.company_name,
    }


@router.get("/status")
async def status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    gateway_url = _get(session, current_user.company_id, "gateway_url")
    if not gateway_url:
        return {"connected": False}

    try:
        await _ping_tally(gateway_url)
        reachable = True
    except Exception:
        reachable = False

    return {
        "connected": reachable,
        "gateway_url": gateway_url,
        "company_name": _get(session, current_user.company_id, "company_name"),
        "reachable": reachable,
    }


@router.delete("/disconnect")
def disconnect(
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    _delete_all(session, current_user.company_id)
    return {"disconnected": True}


@router.get("/companies")
async def list_companies(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Return the list of Tally companies available on the gateway."""
    gateway_url = _get(session, current_user.company_id, "gateway_url")
    if not gateway_url:
        raise HTTPException(status_code=400, detail="Tally not connected")

    try:
        companies = await _ping_tally(gateway_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tally gateway error: {exc}")

    return {"companies": companies, "gateway_url": gateway_url}
