"""
calcom.py - Cal.com provider adapter.

Cal.com MCP server runs at https://mcp.cal.com/mcp.
Auth: OAuth 2.1 + DCR (handled by routes/calcom_connector.py).
Access token stored in ProviderCredential(provider="calcom", key_name="access_token").
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

CALCOM_MCP_URL = "https://mcp.cal.com/mcp"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Cal.com OAuth access token for a company."""
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "calcom",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[calcom_adapter] Failed to decrypt token for company %s: %s", company_id, exc)
        return None


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Cal.com (HTTP transport)."""
    return {
        "name": "calcom",
        "provider": "calcom",
        "url": CALCOM_MCP_URL,
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
