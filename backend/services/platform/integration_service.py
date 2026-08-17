import json
import logging
from typing import Optional

from sqlmodel import Session, select

from models.models import WebhookConfig, CompanySetting, utc_now

logger = logging.getLogger(__name__)

# Standard webhook event types that no-code platforms can subscribe to
STANDARD_EVENT_TYPES = [
    "call.ended",
    "call.started",
    "call.ringing",
    "lead.created",
    "lead.updated",
    "outcome.recorded",
    "tool.executed",
    "appointment.scheduled",
    "quote.sent",
    "quote.opened",
    "quote.accepted",
    "ism.action_dispatched",
]

# Integration platform metadata for guides
INTEGRATION_GUIDES = {
    "make.com": {
        "name": "Make (formerly Integromat)",
        "icon": "make",
        "webhook_setup_url": "https://www.make.com/en/help/webhooks",
        "description": "Connect Rio CRM to 2000+ apps using Make scenarios",
    },
    "zapier": {
        "name": "Zapier",
        "icon": "zapier",
        "webhook_setup_url": "https://zapier.com/apps/webhook/integrations",
        "description": "Create automated workflows between Rio CRM and 6000+ apps",
    },
    "n8n": {
        "name": "n8n",
        "icon": "n8n",
        "webhook_setup_url": "https://docs.n8n.io/integrations/builtin/credentials/webhook/",
        "description": "Self-hosted workflow automation with Rio CRM webhook support",
    },
}


def get_available_events() -> list[dict]:
    return [
        {"key": k, "label": k.replace(".", " ").title()}
        for k in STANDARD_EVENT_TYPES
    ]


def get_integration_platforms() -> dict:
    return INTEGRATION_GUIDES


def get_webhook_config_for_event(session: Session, company_id: int, event_type: str) -> list[WebhookConfig]:
    """Find webhook configs subscribed to a specific event type."""
    all_hooks = session.exec(
        select(WebhookConfig).where(
            WebhookConfig.company_id == company_id,
            WebhookConfig.is_active == True,
        )
    ).all()
    return [h for h in all_hooks if event_type in (h.events or [])]


def get_or_create_webhook_secret(session: Session, company_id: int, webhook_id: int) -> str:
    """Get or generate an HMAC signing secret for a webhook."""
    wh = session.get(WebhookConfig, webhook_id)
    if not wh or wh.company_id != company_id:
        raise ValueError("Webhook not found")
    if wh.secret:
        return wh.secret
    import secrets
    wh.secret = secrets.token_hex(16)
    session.add(wh)
    session.commit()
    return wh.secret


def get_webhook_sample_payload(event_type: str) -> dict:
    """Return a sample JSON payload for the given event type."""
    samples = {
        "call.ended": {
            "event": "call.ended",
            "interaction_id": 123,
            "lead_id": 456,
            "lead_name": "John Doe",
            "agent_id": 789,
            "duration_seconds": 120,
            "outcome": "interested",
            "transcript_excerpt": "Customer asked about pricing...",
            "timestamp": "2025-06-01T10:30:00Z",
        },
        "lead.created": {
            "event": "lead.created",
            "lead_id": 456,
            "lead_name": "Jane Smith",
            "phone": "+14155552671",
            "email": "jane@example.com",
            "source": "web_form",
            "timestamp": "2025-06-01T10:30:00Z",
        },
        "tool.executed": {
            "event": "tool.executed",
            "interaction_id": 123,
            "lead_id": 456,
            "tool_name": "send_communication",
            "tool_args": {"channel": "email", "content": "..."},
            "tool_result": {"status": "sent"},
            "timestamp": "2025-06-01T10:30:00Z",
        },
    }
    return samples.get(event_type, {"event": event_type, "payload": {}, "timestamp": "2025-06-01T10:30:00Z"})
