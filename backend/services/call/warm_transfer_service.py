"""
Warm Transfer Service
Bridges an active AI call to a human ISR in real-time.

Provider routing:
  - Twilio  → redirect active call into <Conference>, dial ISR into same room
  - Exotel  → use Exotel call transfer API
  - EnableX → use EnableX conference/transfer API (fallback to notification only)
  - Plivo   → transfer the active call to provider-hosted XML instructions
  - Vobiz   → transfer the active call to provider-hosted XML instructions
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value
from models.models import Company, Interaction, User, utc_now
from utils.phone import normalize_phone
from utils.url_utils import normalize_base_url

logger = logging.getLogger(__name__)


def _get_telephony_provider(session: Session, company_id: int) -> str:
    # Outbound dialing uses TELEPHONY_ENGINE. TELEPHONY_PROVIDER is retained
    # as a backwards-compatible alias for older installations.
    return (
        get_company_setting_value(session, company_id, "TELEPHONY_ENGINE")
        or get_company_setting_value(session, company_id, "TELEPHONY_PROVIDER")
        or "twilio"
    ).strip().lower()


def _resolve_callback_base(session: Session, company_id: int) -> str:
    if env_domain := os.getenv("DOMAIN"):
        return normalize_base_url(env_domain, "https://localhost:8000")
    company = session.get(Company, company_id)
    domain_source = (company.domain if company and company.domain else None) or "localhost:8000"
    return normalize_base_url(domain_source, "https://localhost:8000")


# Twilio warm transfer via Conference

def _twilio_warm_transfer(
    session: Session,
    company_id: int,
    call_sid: str,
    transfer_to: str,
    conference_name: str,
    callback_base: str,
) -> dict:
    import twilio.twiml.voice_response as twiml_voice
    from twilio.rest import Client as TwilioClient
    from twilio.base.exceptions import TwilioRestException

    account_sid = get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID")
    auth_token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
    from_number = (
        get_company_credential(session, company_id, "TWILIO_PHONE_NUMBER")
        or os.getenv("PHONE_NUMBER_FROM")
    )
    if not all([account_sid, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Twilio credentials not configured")

    client = TwilioClient(account_sid, auth_token)

    # Redirect the existing AI call into a conference room
    conf_twiml = twiml_voice.VoiceResponse()
    dial = conf_twiml.dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=False,
        muted=False,
    )
    client.calls(call_sid).update(twiml=str(conf_twiml))

    # Dial the ISR into the same conference
    isr_twiml = twiml_voice.VoiceResponse()
    isr_dial = isr_twiml.dial()
    isr_dial.conference(
        conference_name,
        start_conference_on_enter=False,
        end_conference_on_exit=True,   # hang up conference when ISR leaves
    )
    try:
        isr_call = client.calls.create(
            to=transfer_to,
            from_=from_number,
            twiml=str(isr_twiml),
        )
    except TwilioRestException as exc:
        if exc.code == 21219:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Twilio trial restriction ({exc.code}): '{transfer_to}' is not a verified number. "
                    "Trial accounts can only call numbers verified in the Twilio console — add the number "
                    "under Phone Numbers → Verified Caller IDs, or upgrade the account (Billing → Upgrade) "
                    "to call any number."
                ),
            )
        raise HTTPException(status_code=502, detail=f"Twilio transfer failed ({exc.code}): {exc.msg}")

    return {
        "provider": "twilio",
        "conference_name": conference_name,
        "isr_call_sid": isr_call.sid,
    }


# Exotel warm transfer

def _exotel_warm_transfer(
    session: Session,
    company_id: int,
    call_sid: str,
    transfer_to: str,
) -> dict:
    import requests as _req

    account_sid = get_company_credential(session, company_id, "EXOTEL_ACCOUNT_SID")
    api_key = get_company_credential(session, company_id, "EXOTEL_API_KEY")
    api_token = get_company_credential(session, company_id, "EXOTEL_API_TOKEN")
    if not all([account_sid, api_key, api_token]):
        raise HTTPException(status_code=400, detail="Exotel credentials not configured")

    # Exotel: transfer an active call to another number
    url = f"https://api.exotel.com/v1/Accounts/{account_sid}/Calls/{call_sid}/Transfer"
    resp = _req.post(
        url,
        auth=(api_key, api_token),
        data={"To": transfer_to},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Exotel transfer failed ({resp.status_code}): {resp.text[:200]}",
        )
    return {"provider": "exotel", "call_sid": call_sid, "transferred_to": transfer_to}


# EnableX — dial ISR in via conference

def _enablex_warm_transfer(
    session: Session,
    company_id: int,
    call_sid: str,
    transfer_to: str,
    conference_name: str,
) -> dict:
    import requests as _req

    app_id = get_company_credential(session, company_id, "ENABLEX_APP_ID")
    app_key = get_company_credential(session, company_id, "ENABLEX_APP_KEY")
    if not all([app_id, app_key]):
        raise HTTPException(status_code=400, detail="EnableX credentials not configured")

    # EnableX conference transfer: add a new participant to an existing room
    url = f"https://api.enablex.io/video/v2/rooms/{conference_name}/dial-out"
    resp = _req.post(
        url,
        auth=(app_id, app_key),
        json={"to": transfer_to, "call_sid": call_sid},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"EnableX transfer failed ({resp.status_code}): {resp.text[:200]}",
        )
    return {"provider": "enablex", "conference_name": conference_name, "transferred_to": transfer_to}


def _transfer_instruction_url(callback_base: str, transfer_to: str) -> str:
    from urllib.parse import urlencode

    return f"{callback_base}/warm-transfer-instructions?{urlencode({'transfer_to': transfer_to})}"


def _plivo_warm_transfer(
    session: Session,
    company_id: int,
    call_sid: str,
    transfer_to: str,
    callback_base: str,
) -> dict:
    import requests as _req

    auth_id = get_company_credential(session, company_id, "PLIVO_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "PLIVO_AUTH_TOKEN")
    if not all([auth_id, auth_token]):
        raise HTTPException(status_code=400, detail="Plivo credentials not configured")

    url = f"https://api.plivo.com/v1/Account/{auth_id}/Call/{call_sid}/"
    response = _req.post(
        url,
        auth=(auth_id, auth_token),
        json={
            "legs": "aleg",
            "aleg_url": _transfer_instruction_url(callback_base, transfer_to),
            "aleg_method": "POST",
        },
        timeout=10,
    )
    if response.status_code not in (200, 201, 202):
        raise HTTPException(
            status_code=502,
            detail=f"Plivo transfer failed ({response.status_code}): {response.text[:300]}",
        )
    return {"provider": "plivo", "call_sid": call_sid, "transferred_to": transfer_to}


def _vobiz_warm_transfer(
    session: Session,
    company_id: int,
    call_sid: str,
    transfer_to: str,
    callback_base: str,
) -> dict:
    import requests as _req

    auth_id = get_company_credential(session, company_id, "VOBIZ_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "VOBIZ_AUTH_TOKEN")
    if not all([auth_id, auth_token]):
        raise HTTPException(status_code=400, detail="Vobiz credentials not configured")

    url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_sid}/"
    response = _req.post(
        url,
        headers={
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
            "Content-Type": "application/json",
        },
        json={
            "legs": "aleg",
            "aleg_url": _transfer_instruction_url(callback_base, transfer_to),
            "aleg_method": "POST",
        },
        timeout=10,
    )
    if response.status_code not in (200, 201, 202):
        raise HTTPException(
            status_code=502,
            detail=f"Vobiz transfer failed ({response.status_code}): {response.text[:300]}",
        )
    return {"provider": "vobiz", "call_sid": call_sid, "transferred_to": transfer_to}


# Public entry point

def execute_warm_transfer(
    session: Session,
    company_id: int,
    actor_user_id: int,
    interaction_id: int,
    transfer_to: str,
    isr_name: Optional[str] = None,
    transfer_to_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Bridge an active call (identified by interaction_id) to a human ISR.
    Updates the interaction metadata with transfer details.
    """
    effective_isr_name = isr_name or transfer_to_name
    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")

    metadata = interaction.metadata_json or {}
    call_sid = metadata.get("call_sid")
    if not call_sid:
        raise HTTPException(status_code=400, detail="No active call SID found for this interaction")

    transfer_to_normalized = normalize_phone(transfer_to)
    conference_name = f"transfer-{interaction_id}-{uuid.uuid4().hex[:8]}"
    callback_base = _resolve_callback_base(session, company_id)
    # Prefer the provider captured on the interaction. This protects an
    # in-progress call if the company setting changes after dialing.
    provider = (
        metadata.get("telephony_provider")
        or metadata.get("telephony_engine")
        or interaction.source
        or _get_telephony_provider(session, company_id)
    ).strip().lower()

    logger.info(
        "[WarmTransfer] interaction=%s provider=%s transfer_to=%s",
        interaction_id, provider, transfer_to_normalized,
    )

    if provider == "exotel":
        result = _exotel_warm_transfer(session, company_id, call_sid, transfer_to_normalized)
    elif provider == "enablex":
        result = _enablex_warm_transfer(session, company_id, call_sid, transfer_to_normalized, conference_name)
    elif provider == "plivo":
        result = _plivo_warm_transfer(
            session, company_id, call_sid, transfer_to_normalized, callback_base
        )
    elif provider == "vobiz":
        result = _vobiz_warm_transfer(
            session, company_id, call_sid, transfer_to_normalized, callback_base
        )
    elif provider == "twilio":
        result = _twilio_warm_transfer(
            session, company_id, call_sid, transfer_to_normalized, conference_name, callback_base
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Warm transfer is not supported for telephony provider '{provider}'",
        )

    # Persist transfer details on the interaction
    interaction.metadata_json = {
        **metadata,
        "warm_transfer": {
            "transferred_to": transfer_to_normalized,
            "isr_name": effective_isr_name,
            "reason": reason,
            "provider": provider,
            "conference_name": conference_name,
            **result,
        },
    }
    interaction.updated_at = utc_now()
    interaction.updated_by = actor_user_id
    session.add(interaction)
    session.commit()

    return {
        "success": True,
        "interaction_id": interaction_id,
        "transfer_to": transfer_to_normalized,
        "provider": provider,
        **result,
    }
