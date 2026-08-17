from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import ContactCreate, User
from services.contact.contact_service import (
    create_contact,
    deactivate_contact,
    get_contact_or_404,
    list_contacts,
    update_contact,
)

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post("")
async def create_contact_route(
    data: ContactCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("contact.manage")),
):
    return create_contact(session, current_user.company_id, current_user.id, data)


@router.get("")
async def list_contacts_route(
    account_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("contact.read")),
):
    return list_contacts(
        session,
        current_user.company_id,
        account_id=account_id,
        lead_id=lead_id,
    )


@router.get("/{contact_id}")
async def get_contact_route(
    contact_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("contact.read")),
):
    return get_contact_or_404(session, current_user.company_id, contact_id)


@router.patch("/{contact_id}")
async def update_contact_route(
    contact_id: int,
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("contact.manage")),
):
    return update_contact(session, current_user.company_id, current_user.id, contact_id, data)


@router.delete("/{contact_id}")
async def deactivate_contact_route(
    contact_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("contact.manage")),
):
    return deactivate_contact(session, current_user.company_id, current_user.id, contact_id)
