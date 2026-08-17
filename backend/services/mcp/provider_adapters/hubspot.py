"""
hubspot.py - HubSpot provider adapter.

HubSpot connects via OAuth (routes/hubspot_oauth.py) and stores tokens in
ProviderCredential(provider="hubspot"). There is no HubSpot MCP server row —
capabilities route to the HubSpot REST API through the REST fallback in
services/mcp/capability_router.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"
HUBSPOT_MCP_URL = "https://mcp.hubspot.com/"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored HubSpot OAuth access token for a company."""
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "hubspot",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,  # noqa: E712
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[hubspot_adapter] Failed to decrypt token for company %s: %s", company_id, exc)
        return None


def build_server_config() -> dict:
    """Return the default MCPServer config dict for HubSpot.

    HubSpot is currently wired as an OAuth + REST provider (no MCP server row
    is created), so this config is informational / forward-compatible.
    """
    return {
        "name": "hubspot",
        "provider": "hubspot",
        "url": HUBSPOT_MCP_URL,
        "transport": "http",
        "auth_type": "oauth2",
        "config_json": {},
        "capabilities_json": [
            "search_prospects",
            "create_crm_contact",
            "update_crm_contact",
            "crm_query",
        ],
        "priority": 85,
    }
