from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Contact, ContactCreate, utc_now

logger = logging.getLogger(__name__)


def create_contact(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: ContactCreate,
) -> Contact:
    now = utc_now()
    contact = Contact(
        company_id=company_id,
        account_id=data.account_id,
        lead_id=data.lead_id,
        owner_user_id=actor_user_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        designation=data.designation,
        department=data.department,
        is_primary=data.is_primary,
        is_active=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def get_contact_or_404(
    session: Session,
    company_id: int,
    contact_id: int,
) -> Contact:
    contact = session.exec(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.company_id == company_id,
        )
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


def list_contacts(
    session: Session,
    company_id: int,
    account_id: Optional[int] = None,
    lead_id: Optional[int] = None,
) -> list[Contact]:
    query = select(Contact).where(
        Contact.company_id == company_id,
        Contact.is_active == True,
    )
    if account_id:
        query = query.where(Contact.account_id == account_id)
    if lead_id:
        query = query.where(Contact.lead_id == lead_id)
    return session.exec(query.order_by(Contact.created_at.desc())).all()


def update_contact(
    session: Session,
    company_id: int,
    actor_user_id: int,
    contact_id: int,
    data: dict,
) -> Contact:
    contact = get_contact_or_404(session, company_id, contact_id)

    allowed_fields = {
        "name", "email", "phone", "designation", "department",
        "is_primary", "preferred_language", "notes", "account_id", "lead_id",
    }
    for field, value in data.items():
        if field in allowed_fields:
            setattr(contact, field, value)

    contact.updated_at = utc_now()
    contact.updated_by = actor_user_id
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def deactivate_contact(
    session: Session,
    company_id: int,
    actor_user_id: int,
    contact_id: int,
) -> Contact:
    contact = get_contact_or_404(session, company_id, contact_id)
    contact.is_active = False
    contact.updated_at = utc_now()
    contact.updated_by = actor_user_id
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact
