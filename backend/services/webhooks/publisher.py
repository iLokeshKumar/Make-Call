import asyncio
import hashlib
import json
import logging
from typing import Any

from database import engine as _engine
from sqlmodel import Session as _Session, select
from models.models import WebhookConfig, WebhookDeliveryLog
from services.webhooks.delivery import deliver

logger = logging.getLogger(__name__)

async def publish(company_id: int, event_type: str, payload: dict[str, Any],
                  *, agent_filter: str | None = None, outcome_filter: str | None = None) -> None:
    """Fan out `payload` to every active WebhookConfig subscribed to `event_type`
    for the given company_id. Subscribed means `event_type` is in the `events` list."""
    try:
        with _Session(_engine) as s:
            hooks = s.exec(
                select(WebhookConfig).where(
                    WebhookConfig.company_id == company_id,
                    WebhookConfig.is_active == True,
                )
            ).all()
    except Exception as exc:
        logger.debug("[webhooks] DB read failed: %s", exc)
        return

    body = json.dumps(payload, default=str).encode()

    for hook in hooks:
        if event_type not in hook.events:
            continue
        # Optional filters
        if agent_filter and hook.agent_filter and hook.agent_filter != agent_filter:
            continue
        if outcome_filter and hook.outcome_filter and hook.outcome_filter != outcome_filter:
            continue

        payload_hash = hashlib.sha256(body).hexdigest()
        result = await deliver(
            webhook_url=hook.url,
            event_type=event_type,
            payload=payload,
            secret=hook.secret,
            timeout=float(hook.timeout_seconds or 10),
        )
        _log(s, hook.id, event_type, payload_hash, result)


def _log(s: _Session, hook_id: int, event_type: str, payload_hash: str, result: dict) -> None:
    try:
        # Get the webhook to fill in company_id
        hook = s.get(WebhookConfig, hook_id)
        if hook:
            s.add(WebhookDeliveryLog(
                company_id=hook.company_id,
                webhook_id=hook_id,
                event_type=event_type,
                payload_hash=payload_hash,
                http_status=result.get("http_status"),
                response_ms=result.get("response_ms"),
                error=result.get("error"),
            ))
            s.commit()
    except Exception as exc:
        logger.debug("[webhooks] delivery log write failed: %s", exc)