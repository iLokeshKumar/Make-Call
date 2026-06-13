"""India DLT compliance application tracking and Truecaller integration."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import ComplianceApplication

logger = logging.getLogger(__name__)


def create_application(
    session: Session,
    company_id: int,
    actor_user_id: int,
    application_type: str,
    provider: str,
    entity_name: str,
    entity_id: str | None = None,
    header_id: str | None = None,
    template_id: str | None = None,
    notes: str | None = None,
) -> ComplianceApplication:
    app = ComplianceApplication(
        company_id=company_id,
        application_type=application_type,
        status="draft",
        provider=provider,
        entity_name=entity_name,
        entity_id=entity_id,
        header_id=header_id,
        template_id=template_id,
        notes=notes,
    )
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def list_applications(
    session: Session,
    company_id: int,
    status_filter: str | None = None,
) -> list[ComplianceApplication]:
    q = select(ComplianceApplication).where(ComplianceApplication.company_id == company_id)
    if status_filter:
        q = q.where(ComplianceApplication.status == status_filter)
    return session.exec(q.order_by(ComplianceApplication.created_at.desc())).all()


def get_application(session: Session, company_id: int, app_id: int) -> ComplianceApplication:
    app = session.get(ComplianceApplication, app_id)
    if not app or app.company_id != company_id:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def submit_application(
    session: Session,
    company_id: int,
    app_id: int,
    actor_user_id: int,
    document_urls: dict | None = None,
) -> ComplianceApplication:
    app = get_application(session, company_id, app_id)
    import datetime
    app.status = "submitted"
    app.submitted_at = datetime.datetime.now(datetime.timezone.utc)
    if document_urls:
        app.document_urls = document_urls
    app.updated_by = actor_user_id
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def update_application_status(
    session: Session,
    company_id: int,
    app_id: int,
    status: str,
    actor_user_id: int,
    notes: str | None = None,
) -> ComplianceApplication:
    app = get_application(session, company_id, app_id)
    import datetime
    app.status = status
    if status == "approved":
        app.approved_at = datetime.datetime.now(datetime.timezone.utc)
    if notes:
        app.notes = (app.notes or "") + f"\n{notes}"
    app.updated_by = actor_user_id
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


# ── Truecaller Verification (stub) ──


def verify_with_truecaller(
    session: Session,
    company_id: int,
    phone: str,
    business_name: str,
) -> dict:
    """
    Submit a phone number for Truecaller business verification.

    This is a stub — Truecaller requires a signed partnership agreement
    and API credentials. When integrated, this will:
    1. Call Truecaller Business API
    2. Return verification status + branded caller ID details
    """
    logger.info("[Truecaller] Verification requested for %s (company=%d): %s", phone, company_id, business_name)
    return {
        "status": "submitted",
        "phone": phone,
        "business_name": business_name,
        "note": "Truecaller API integration requires partnership — contact Truecaller Business for credentials.",
    }
