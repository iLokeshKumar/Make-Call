"""SIP trunk management — CRUD + connectivity."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import SIPTrunk

logger = logging.getLogger(__name__)


def create_sip_trunk(
    session: Session,
    company_id: int,
    actor_user_id: int,
    name: str,
    host: str,
    port: int = 5060,
    transport: str = "udp",
    provider: str = "generic_sip",
    username: str | None = None,
    password: str | None = None,
    sip_uri: str | None = None,
    outbound_proxy: str | None = None,
    codecs: str = "PCMU,PCMA",
    dtmf_mode: str = "rfc2833",
    is_default: bool = False,
) -> SIPTrunk:
    existing = session.exec(
        select(SIPTrunk).where(
            SIPTrunk.company_id == company_id,
            SIPTrunk.name == name,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="SIP trunk name already exists")

    if is_default:
        _clear_default(session, company_id)

    password_encrypted = None
    if password:
        from utils.encryption import encrypt_value
        try:
            password_encrypted = encrypt_value(password)
        except Exception:
            password_encrypted = password

    trunk = SIPTrunk(
        company_id=company_id,
        name=name,
        provider=provider,
        host=host,
        port=port,
        transport=transport,
        username=username,
        password_encrypted=password_encrypted,
        sip_uri=sip_uri,
        outbound_proxy=outbound_proxy,
        codecs=codecs,
        dtmf_mode=dtmf_mode,
        is_default=is_default,
    )
    session.add(trunk)
    session.commit()
    session.refresh(trunk)
    return trunk


def list_sip_trunks(session: Session, company_id: int) -> list[SIPTrunk]:
    return session.exec(
        select(SIPTrunk).where(
            SIPTrunk.company_id == company_id,
            SIPTrunk.status == "active",
        )
    ).all()


def get_sip_trunk(session: Session, company_id: int, trunk_id: int) -> SIPTrunk:
    trunk = session.get(SIPTrunk, trunk_id)
    if not trunk or trunk.company_id != company_id:
        raise HTTPException(status_code=404, detail="SIP trunk not found")
    return trunk


def update_sip_trunk(
    session: Session,
    company_id: int,
    trunk_id: int,
    actor_user_id: int,
    **updates,
) -> SIPTrunk:
    trunk = get_sip_trunk(session, company_id, trunk_id)
    allowed = {"name", "host", "port", "transport", "username", "sip_uri",
               "outbound_proxy", "codecs", "dtmf_mode", "status", "is_default"}

    if updates.get("is_default"):
        _clear_default(session, company_id)

    if "password" in updates and updates["password"]:
        from utils.encryption import encrypt_value
        try:
            updates["password_encrypted"] = encrypt_value(updates.pop("password"))
        except Exception:
            updates["password_encrypted"] = updates.pop("password")

    for key, value in updates.items():
        if key in allowed and value is not None:
            setattr(trunk, key, value)

    trunk.updated_by = actor_user_id
    session.add(trunk)
    session.commit()
    session.refresh(trunk)
    return trunk


def delete_sip_trunk(session: Session, company_id: int, trunk_id: int) -> None:
    trunk = get_sip_trunk(session, company_id, trunk_id)
    trunk.status = "disabled"
    session.add(trunk)
    session.commit()


def get_default_sip_trunk(session: Session, company_id: int) -> SIPTrunk | None:
    return session.exec(
        select(SIPTrunk).where(
            SIPTrunk.company_id == company_id,
            SIPTrunk.is_default == True,
            SIPTrunk.status == "active",
        )
    ).first()


def _clear_default(session: Session, company_id: int) -> None:
    session.exec(
        select(SIPTrunk).where(
            SIPTrunk.company_id == company_id,
            SIPTrunk.is_default == True,
        )
    ).all()
    session.exec(
        f"UPDATE sip_trunks SET is_default = FALSE WHERE company_id = {company_id}"
    )
    session.commit()
