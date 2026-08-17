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
    """
    import requests
    from credentials_service import get_credential
    from config import settings

    logger.info("[Truecaller] Verification requested for %s (company=%d): %s", phone, company_id, business_name)

    # 1. Retrieve credentials securely
    key_id = get_credential(session, company_id, "TRUECALLER_KEY_ID")
    api_key = get_credential(session, company_id, "TRUECALLER_API_KEY")
    client_account_id = get_credential(session, company_id, "TRUECALLER_CLIENT_ACCOUNT_ID")
    
    # Fallback to config settings/env
    if not key_id:
        key_id = settings.TRUECALLER_KEY_ID
    if not api_key:
        api_key = settings.TRUECALLER_API_KEY
    if not client_account_id:
        client_account_id = settings.TRUECALLER_CLIENT_ACCOUNT_ID

    if not (key_id and api_key and client_account_id):
        logger.warning("[Truecaller] Credentials missing for company=%d", company_id)
        return {
            "status": "error",
            "message": "Truecaller credentials missing in company settings.",
            "note": "Truecaller API integration requires partnership — contact Truecaller Business for credentials.",
        }

    base_url = "https://enterprise-portal-noneu.truecaller.com/api/v1"
    
    try:
        # Step 2: Auth handshake
        auth_res = requests.post(
            f"{base_url}/auth/token",
            json={"keyId": key_id, "apiKey": api_key},
            timeout=5
        )
        if not auth_res.ok:
            logger.error("[Truecaller] Auth handshake failed: %s", auth_res.text)
            return {"status": "error", "message": "Truecaller Auth handshake failed"}
            
        token = auth_res.json().get("accessToken")
        
        # Step 3: Register Caller ID Number
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "numbers": [{
                "phoneNumber": phone,
                "countryCode": "IN",  # Default to India as optimized, can parse or infer prefix
                "label": business_name,
                "features": ["CALLER_ID"]
            }]
        }
        reg_res = requests.post(
            f"{base_url}/clients/{client_account_id}/number_management/numbers",
            json=payload,
            headers=headers,
            timeout=5
        )
        if reg_res.ok:
            logger.info("[Truecaller] Verification submitted successfully for %s", phone)
            return {
                "status": "submitted",
                "phone": phone,
                "business_name": business_name,
                "details": reg_res.json()
            }
        logger.error("[Truecaller] Number submission failed: %s", reg_res.text)
        return {"status": "failed", "error": reg_res.text}
        
    except Exception as e:
        logger.exception("[Truecaller] Connection to Truecaller API failed")
        return {"status": "error", "message": f"Connection failed: {str(e)}"}
