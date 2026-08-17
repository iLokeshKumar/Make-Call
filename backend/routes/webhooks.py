from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select
from typing import List, Optional
from database import get_session
from models.models import WebhookConfig, WebhookDeliveryLog, Company, User
from schemas.webhooks import WebhookConfigCreate, WebhookConfigRead, WebhookConfigUpsert, WebhookDeliveryLogRead
from auth import get_current_user
import hashlib
import hmac
import time
import uuid
import json
import logging
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger(__name__)

def _mask_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return None
    if len(secret) <= 8:
        return "****"
    return secret[:4] + "****" + secret[-4:]

@router.get("/webhooks", response_model=List[WebhookConfigRead])
def list_webhooks(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    List all webhooks for a company (secret masked).
    """
    statement = select(WebhookConfig).where(
        WebhookConfig.company_id == current_user.company_id,
        WebhookConfig.is_active == True,
    )
    webhooks = session.exec(statement).all()
    # Mask secret in response
    for wh in webhooks:
        wh.secret = _mask_secret(wh.secret)
    return webhooks

@router.post("/webhooks", response_model=WebhookConfigRead, status_code=status.HTTP_201_CREATED)
def create_webhook(
    webhook_in: WebhookConfigCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new webhook configuration.
    Validates URL and requires secret >= 16 chars if provided.
    """
    # Validate secret length if provided
    if webhook_in.secret is not None and len(webhook_in.secret) < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret must be at least 16 characters long if provided",
        )
    # Basic URL validation (could be more robust)
    if not webhook_in.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )
    webhook = WebhookConfig.from_orm(webhook_in)
    webhook.company_id = current_user.company_id
    session.add(webhook)
    session.commit()
    session.refresh(webhook)
    webhook.secret = _mask_secret(webhook.secret)
    return webhook

@router.patch("/webhooks/{webhook_id}", response_model=WebhookConfigRead)
def update_webhook(
    webhook_id: int,
    webhook_in: WebhookConfigUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Update a webhook configuration (partial).
    """
    webhook = session.get(WebhookConfig, webhook_id)
    if not webhook or webhook.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )
    # Validate secret length if provided
    if webhook_in.secret is not None and len(webhook_in.secret) < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret must be at least 16 characters long if provided",
        )
    # Update fields that are set
    update_data = webhook_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(webhook, field, value)
    session.add(webhook)
    session.commit()
    session.refresh(webhook)
    webhook.secret = _mask_secret(webhook.secret)
    return webhook

@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete a webhook by setting is_active to False.
    """
    webhook = session.get(WebhookConfig, webhook_id)
    if not webhook or webhook.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )
    webhook.is_active = False
    session.add(webhook)
    session.commit()
    return None

@router.post("/webhooks/{webhook_id}/test", response_model=dict)
def test_webhook(
    webhook_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Fire a synthetic event to the webhook URL and return delivery result.
    """
    webhook = session.get(WebhookConfig, webhook_id)
    if not webhook or webhook.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )
    if not webhook.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook is inactive",
        )
    # Synthetic payload
    payload = {
        "event_type": "webhook.test",
        "timestamp": datetime.utcnow().isoformat(),
        "webhook_id": webhook.id,
        "company_id": webhook.company_id,
        "test": True,
    }
    # Use delivery service
    from services.webhooks.delivery import deliver
    import asyncio
    # Since we're in a sync context, we run the async function
    result = asyncio.run(deliver(
        webhook_url=webhook.url,
        event_type="webhook.test",
        payload=payload,
        secret=webhook.secret,
        timeout=float(webhook.timeout_seconds or 10),
    ))
    # Log the delivery attempt
    from services.webhooks.publisher import _log
    with session as s:
        _log(s, webhook.id, "webhook.test", hashlib.sha256(json.dumps(payload).encode()).hexdigest(), result)
    return result

@router.get("/webhooks/delivery-logs", response_model=List[WebhookDeliveryLogRead])
def get_delivery_logs(
    limit: int = Query(100, lte=1000),
    offset: int = Query(0, lte=10000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Paginated delivery log feed for a company.
    """
    statement = select(WebhookDeliveryLog).where(
        WebhookDeliveryLog.company_id == current_user.company_id
    ).order_by(WebhookDeliveryLog.created_at.desc()).offset(offset).limit(limit)
    logs = session.exec(statement).all()
    return logs

# Cleanup function to be called by automation worker
def delivery_log_cleanup(session: Session) -> int:
    """
    Delete WebhookDeliveryLog rows older than 7 days.
    Returns number of rows deleted.
    """
    cutoff = datetime.utcnow() - timedelta(days=7)
    statement = select(WebhookDeliveryLog).where(WebhookDeliveryLog.created_at < cutoff)
    logs_to_delete = session.exec(statement).all()
    for log in logs_to_delete:
        session.delete(log)
    session.commit()
    return len(logs_to_delete)