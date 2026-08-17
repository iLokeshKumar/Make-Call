"""SIP trunk management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from auth import get_current_active_user, PermissionChecker
from database import get_session
from models.models import User
from services.telephony.sip_trunk_service import (
    create_sip_trunk,
    list_sip_trunks,
    get_sip_trunk,
    update_sip_trunk,
    delete_sip_trunk,
)

router = APIRouter(prefix="/crm/sip-trunks", tags=["sip-trunks"])


class SIPTrunkCreate(BaseModel):
    name: str
    host: str
    port: int = 5060
    transport: str = "udp"
    provider: str = "generic_sip"
    username: str | None = None
    password: str | None = None
    sip_uri: str | None = None
    outbound_proxy: str | None = None
    codecs: str = "PCMU,PCMA"
    dtmf_mode: str = "rfc2833"
    is_default: bool = False


class SIPTrunkUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    transport: str | None = None
    username: str | None = None
    password: str | None = None
    sip_uri: str | None = None
    outbound_proxy: str | None = None
    codecs: str | None = None
    dtmf_mode: str | None = None
    status: str | None = None
    is_default: bool | None = None


@router.post("")
async def api_create_sip_trunk(
    data: SIPTrunkCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    trunk = create_sip_trunk(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        name=data.name,
        host=data.host,
        port=data.port,
        transport=data.transport,
        provider=data.provider,
        username=data.username,
        password=data.password,
        sip_uri=data.sip_uri,
        outbound_proxy=data.outbound_proxy,
        codecs=data.codecs,
        dtmf_mode=data.dtmf_mode,
        is_default=data.is_default,
    )
    return {"id": trunk.id, "name": trunk.name, "host": trunk.host}


@router.get("")
async def api_list_sip_trunks(
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    trunks = list_sip_trunks(session, current_user.company_id)
    return [
        {
            "id": t.id,
            "name": t.name,
            "provider": t.provider,
            "host": t.host,
            "port": t.port,
            "transport": t.transport,
            "status": t.status,
            "is_default": t.is_default,
        }
        for t in trunks
    ]


@router.get("/{trunk_id}")
async def api_get_sip_trunk(
    trunk_id: int,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    trunk = get_sip_trunk(session, current_user.company_id, trunk_id)
    return {
        "id": trunk.id,
        "name": trunk.name,
        "provider": trunk.provider,
        "host": trunk.host,
        "port": trunk.port,
        "transport": trunk.transport,
        "sip_uri": trunk.sip_uri,
        "outbound_proxy": trunk.outbound_proxy,
        "codecs": trunk.codecs,
        "dtmf_mode": trunk.dtmf_mode,
        "status": trunk.status,
        "is_default": trunk.is_default,
    }


@router.patch("/{trunk_id}")
async def api_update_sip_trunk(
    trunk_id: int,
    data: SIPTrunkUpdate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    trunk = update_sip_trunk(
        session=session,
        company_id=current_user.company_id,
        trunk_id=trunk_id,
        actor_user_id=current_user.id,
        **data.model_dump(exclude_none=True),
    )
    return {"id": trunk.id, "status": "updated"}


@router.delete("/{trunk_id}")
async def api_delete_sip_trunk(
    trunk_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    delete_sip_trunk(session, current_user.company_id, trunk_id)
    return {"status": "disabled"}
