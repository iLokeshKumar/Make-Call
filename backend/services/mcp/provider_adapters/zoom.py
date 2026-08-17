from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

# Zoom Meetings MCP server — remote streamable-HTTP endpoint hosted by Zoom.
# Registered in the company MCPServer registry after the OAuth flow completes.
ZOOM_MEETINGS_MCP_URL = "https://mcp.zoom.us/mcp/meeting/streamable"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Zoom OAuth access token for a company."""
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "zoom",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[zoom_adapter] Failed to decrypt access token for company %s: %s", company_id, exc)
        return None


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Zoom Meetings (HTTP transport)."""
    return {
        "name": "zoom",
        "provider": "zoom",
        "url": ZOOM_MEETINGS_MCP_URL,
        "transport": "http",
        "auth_type": "oauth2",
        "config_json": {},
        "capabilities_json": [
            "search_meetings",
            "get_meeting_assets",
            "list_meeting_recordings",
            "get_recording_resource",
        ],
        "priority": 70,
    }
