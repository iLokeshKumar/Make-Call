import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import ProviderCredentialCreate, ProviderCredentialUpdate, User
from services.platform.provider_credentials_service import (
    create_credential, delete_credential, get_credential,
    list_credentials, to_masked_read, update_credential,
)

router = APIRouter(prefix="/crm/provider-credentials", tags=["Provider Credentials"])
logger = logging.getLogger(__name__)


@router.get("")
def list_all(
    provider: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    creds = list_credentials(session, current_user.company_id, provider=provider)
    return [to_masked_read(c) for c in creds]


@router.post("", status_code=201)
def create(
    body: ProviderCredentialCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cred = create_credential(session, current_user.company_id, body)
    return to_masked_read(cred)


@router.get("/{credential_id}")
def get_one(
    credential_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cred = get_credential(session, current_user.company_id, credential_id)
    if not cred:
        raise HTTPException(status_code=404)
    return to_masked_read(cred)


@router.put("/{credential_id}")
def update_one(
    credential_id: int,
    body: ProviderCredentialUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cred = update_credential(session, current_user.company_id, credential_id, body)
    if not cred:
        raise HTTPException(status_code=404)
    return to_masked_read(cred)


@router.delete("/{credential_id}")
def delete_one(
    credential_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not delete_credential(session, current_user.company_id, credential_id):
        raise HTTPException(status_code=404)
    return {"ok": True}
