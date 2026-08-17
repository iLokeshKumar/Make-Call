"""
rocketreach_mcp.py - RocketReach MCP provider adapter.

MCP server: https://rocketreach.co/mcp
Auth: OAuth 2.1 + DCR (handled by routes/rocketreach_mcp_connector.py).
Token stored in ProviderCredential(provider="rocketreach_mcp", key_name="access_token").
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

ROCKETREACH_MCP_URL = "https://mcp.rocketreach.co/mcp"


def get_token(session: Session, company_id: int) -> Optional[str]:
    from models.models import ProviderCredential
    cred = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == "rocketreach_mcp",
            ProviderCredential.key_name == "access_token",
            ProviderCredential.is_active == True,
        )
    ).first()
    if not cred:
        return None
    try:
        return decrypt_value(cred.value_encrypted)
    except Exception as exc:
        logger.warning("[rocketreach_mcp_adapter] Failed to decrypt token for company %s: %s", company_id, exc)
        return None
