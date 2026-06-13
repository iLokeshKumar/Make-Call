import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import User
from services.platform.integration_service import (
    get_available_events, get_integration_platforms,
    get_or_create_webhook_secret, get_webhook_sample_payload,
)

router = APIRouter(prefix="/crm/integrations", tags=["Integrations"])
logger = logging.getLogger(__name__)


@router.get("/events")
def list_events(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List available webhook event types for no-code integration."""
    return get_available_events()


@router.get("/platforms")
def list_platforms(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List supported no-code integration platforms."""
    return get_integration_platforms()


@router.get("/sample-payload/{event_type}")
def sample_payload(
    event_type: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a sample JSON payload for a webhook event type."""
    return get_webhook_sample_payload(event_type)


@router.post("/webhooks/{webhook_id}/secret")
def rotate_secret(
    webhook_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get or generate a webhook signing secret."""
    try:
        secret = get_or_create_webhook_secret(session, current_user.company_id, webhook_id)
        return {"webhook_id": webhook_id, "secret": secret}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))
