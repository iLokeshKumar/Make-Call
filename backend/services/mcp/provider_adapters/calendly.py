from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

CALENDLY_MCP_URL = "https://mcp.calendly.com"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Calendly OAuth access token for a company."""
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "calendly",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[calendly_adapter] Failed to decrypt token for company %s: %s", company_id, exc)
        return None


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Calendly (HTTP transport)."""
    return {
        "name": "calendly",
        "provider": "calendly",
        "url": CALENDLY_MCP_URL,
        "transport": "http",
        "auth_type": "oauth2",
        "config_json": {},
        "capabilities_json": [
            "schedule_meeting",
            "get_availability",
            "list_bookings",
            "reschedule_meeting",
            "cancel_meeting",
        ],
        "priority": 80,
    }
