"""
zoho.py - Zoho CRM provider adapter.

Zoho exposes an MCP server at https://mcp.zoho.com/ with OAuth 2.0.
Tokens are stored in ProviderCredential rows (provider="zoho", key_name="access_token").
The OAuth flow is handled by routes/zoho_oauth.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

ZOHO_MCP_URL = "https://mcp.zoho.com/"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return the stored Zoho access token for a company."""
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "zoho",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[zoho_adapter] Failed to decrypt token for company %s: %s", company_id, exc)
        return None


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Zoho CRM."""
    return {
        "name": "zoho_crm",
        "provider": "zoho",
        "url": ZOHO_MCP_URL,
        "transport": "http",
        "auth_type": "oauth2",
        "capabilities_json": [
            "crm_read",
            "create_crm_contact",
            "update_crm_contact",
            "crm_query",
            "crm_workflow",
        ],
        "priority": 90,
    }
