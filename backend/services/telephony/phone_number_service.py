"""Provider abstraction for buying, listing, and releasing phone numbers."""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from credentials_service import get_company_credential
from models.models import ProviderPhoneNumber, VoiceAgent, utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Twilio
# ---------------------------------------------------------------------------

def _twilio_client(session: Session, company_id: int):
    from twilio.rest import Client as TwilioClient
    sid = get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID")
    token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise HTTPException(status_code=400, detail="Twilio credentials not configured")
    return TwilioClient(sid, token)


def twilio_search_available(
    session: Session,
    company_id: int,
    country: str = "US",
    area_code: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    client = _twilio_client(session, company_id)
    kwargs: dict = {"limit": limit, "voice_enabled": True}
    if area_code:
        kwargs["area_code"] = area_code
    numbers = client.available_phone_numbers(country).local.list(**kwargs)
    return [
        {
            "number": n.phone_number,
            "friendly_name": n.friendly_name,
            "capabilities": {
                "voice": n.capabilities.get("voice", False),
                "sms": n.capabilities.get("SMS", False),
                "mms": n.capabilities.get("MMS", False),
            },
            "monthly_cost": None,
            "provider": "twilio",
        }
        for n in numbers
    ]


def twilio_buy_number(
    session: Session,
    company_id: int,
    actor_user_id: int,
    number: str,
) -> ProviderPhoneNumber:
    client = _twilio_client(session, company_id)
    try:
        purchased = client.incoming_phone_numbers.create(phone_number=number)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Twilio purchase failed: {exc}")

    row = ProviderPhoneNumber(
        company_id=company_id,
        provider="twilio",
        number=purchased.phone_number,
        sid=purchased.sid,
        friendly_name=purchased.friendly_name,
        capabilities={
            "voice": purchased.capabilities.get("voice", False),
            "sms": purchased.capabilities.get("SMS", False),
            "mms": purchased.capabilities.get("MMS", False),
        },
        status="active",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("[PhoneNumbers] Twilio number purchased: %s company=%s", number, company_id)
    return row


def twilio_release_number(session: Session, company_id: int, row: ProviderPhoneNumber) -> None:
    if row.sid:
        try:
            client = _twilio_client(session, company_id)
            client.incoming_phone_numbers(row.sid).delete()
        except Exception as exc:
            logger.warning("[PhoneNumbers] Twilio release failed (continuing): %s", exc)
    row.status = "released"
    row.updated_at = utc_now()
    session.add(row)
    session.commit()


# ---------------------------------------------------------------------------
# Plivo
# ---------------------------------------------------------------------------

def _plivo_client(session: Session, company_id: int):
    try:
        import plivo
    except ImportError:
        raise HTTPException(status_code=500, detail="plivo package not installed")
    auth_id = get_company_credential(session, company_id, "PLIVO_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "PLIVO_AUTH_TOKEN")
    if not auth_id or not auth_token:
        raise HTTPException(status_code=400, detail="Plivo credentials not configured")
    return plivo.RestClient(auth_id, auth_token)


def plivo_search_available(
    session: Session,
    company_id: int,
    country: str = "US",
    area_code: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    client = _plivo_client(session, company_id)
    kwargs: dict = {"country_iso": country, "type": "local", "limit": limit, "services": "voice"}
    if area_code:
        kwargs["region"] = area_code
    try:
        resp = client.numbers.search(**kwargs)
        objects = resp.get("objects", [])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plivo search failed: {exc}")
    return [
        {
            "number": n.get("number", ""),
            "friendly_name": n.get("number", ""),
            "capabilities": {
                "voice": "voice" in (n.get("services", "")),
                "sms": "sms" in (n.get("services", "")),
                "mms": False,
            },
            "monthly_cost": n.get("monthly_rental_rate"),
            "provider": "plivo",
        }
        for n in objects
    ]


def plivo_buy_number(
    session: Session,
    company_id: int,
    actor_user_id: int,
    number: str,
) -> ProviderPhoneNumber:
    client = _plivo_client(session, company_id)
    try:
        client.numbers.buy(number=number)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plivo purchase failed: {exc}")

    row = ProviderPhoneNumber(
        company_id=company_id,
        provider="plivo",
        number=number,
        sid=number,
        friendly_name=number,
        capabilities={"voice": True, "sms": True, "mms": False},
        status="active",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def plivo_release_number(session: Session, company_id: int, row: ProviderPhoneNumber) -> None:
    if row.sid:
        try:
            client = _plivo_client(session, company_id)
            client.numbers.unrent(number=row.sid)
        except Exception as exc:
            logger.warning("[PhoneNumbers] Plivo release failed (continuing): %s", exc)
    row.status = "released"
    row.updated_at = utc_now()
    session.add(row)
    session.commit()


# ---------------------------------------------------------------------------
# Exotel — no purchase API; user registers an existing DID
# ---------------------------------------------------------------------------

def exotel_register_number(
    session: Session,
    company_id: int,
    actor_user_id: int,
    number: str,
    friendly_name: Optional[str] = None,
) -> ProviderPhoneNumber:
    row = ProviderPhoneNumber(
        company_id=company_id,
        provider="exotel",
        number=number,
        sid=None,
        friendly_name=friendly_name or number,
        capabilities={"voice": True, "sms": True, "mms": False},
        status="active",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Vobiz — register existing DID (API docs TBD)
# ---------------------------------------------------------------------------

def vobiz_register_number(
    session: Session,
    company_id: int,
    actor_user_id: int,
    number: str,
    friendly_name: Optional[str] = None,
) -> ProviderPhoneNumber:
    """Register a Vobiz DID. When Vobiz exposes a number purchase API this will be extended."""
    row = ProviderPhoneNumber(
        company_id=company_id,
        provider="vobiz",
        number=number,
        sid=None,
        friendly_name=friendly_name or number,
        capabilities={"voice": True, "sms": False, "mms": False},
        status="active",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Unified helpers used by routes
# ---------------------------------------------------------------------------

PURCHASE_PROVIDERS = {"twilio", "plivo"}
REGISTER_PROVIDERS = {"exotel", "vobiz"}


def search_available_numbers(
    session: Session,
    company_id: int,
    provider: str,
    country: str = "US",
    area_code: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    if provider == "twilio":
        return twilio_search_available(session, company_id, country, area_code, limit)
    if provider == "plivo":
        return plivo_search_available(session, company_id, country, area_code, limit)
    if provider in REGISTER_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"{provider} does not support number search. Use 'register' to add an existing DID.")
    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


def buy_or_register_number(
    session: Session,
    company_id: int,
    actor_user_id: int,
    provider: str,
    number: str,
    friendly_name: Optional[str] = None,
) -> ProviderPhoneNumber:
    # Prevent duplicates
    existing = session.exec(
        select(ProviderPhoneNumber).where(
            ProviderPhoneNumber.company_id == company_id,
            ProviderPhoneNumber.provider == provider,
            ProviderPhoneNumber.number == number,
            ProviderPhoneNumber.status == "active",
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Number already registered for this company")

    if provider == "twilio":
        return twilio_buy_number(session, company_id, actor_user_id, number)
    if provider == "plivo":
        return plivo_buy_number(session, company_id, actor_user_id, number)
    if provider == "exotel":
        return exotel_register_number(session, company_id, actor_user_id, number, friendly_name)
    if provider == "vobiz":
        return vobiz_register_number(session, company_id, actor_user_id, number, friendly_name)
    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


def release_number(session: Session, company_id: int, number_id: int) -> None:
    row = session.exec(
        select(ProviderPhoneNumber).where(
            ProviderPhoneNumber.id == number_id,
            ProviderPhoneNumber.company_id == company_id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Phone number not found")
    if row.status == "released":
        raise HTTPException(status_code=400, detail="Number already released")

    if row.provider == "twilio":
        twilio_release_number(session, company_id, row)
    elif row.provider == "plivo":
        plivo_release_number(session, company_id, row)
    else:
        row.status = "released"
        row.updated_at = utc_now()
        session.add(row)
        session.commit()


def assign_number_to_agent(
    session: Session,
    company_id: int,
    number_id: int,
    agent_id: Optional[int],
    actor_user_id: int,
) -> ProviderPhoneNumber:
    row = session.exec(
        select(ProviderPhoneNumber).where(
            ProviderPhoneNumber.id == number_id,
            ProviderPhoneNumber.company_id == company_id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if agent_id is not None:
        agent = session.exec(
            select(VoiceAgent).where(
                VoiceAgent.id == agent_id,
                VoiceAgent.company_id == company_id,
            )
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Voice agent not found")

    row.assigned_agent_id = agent_id
    row.updated_at = utc_now()
    row.updated_by = actor_user_id
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
