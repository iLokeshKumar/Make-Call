"""
microsoft.py - Microsoft 365 provider adapter.

Microsoft connects via OAuth (routes/microsoft_oauth.py) and stores tokens in
ProviderCredential(provider="microsoft"). There is no Microsoft MCP server row —
capabilities route to the Microsoft Graph REST API through the REST fallback in
services/mcp/capability_router.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)

MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def get_token(session: Session, company_id: int) -> Optional[str]:
    """Return a fresh Microsoft 365 access token, auto-refreshing when expired.

    Delegates to routes.microsoft_oauth.get_or_refresh_microsoft_token, which
    exchanges the stored refresh token when the access token is expired or
    close to expiry, so capability routing and executors never read a stale
    token after ~1 hour.
    """
    from routes.microsoft_oauth import get_or_refresh_microsoft_token
    return get_or_refresh_microsoft_token(session, company_id)


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Microsoft 365.

    Microsoft is currently wired as an OAuth + Graph REST provider (no MCP
    server row is created), so this config is informational / forward-compatible.
    """
    return {
        "name": "microsoft",
        "provider": "microsoft",
        "url": MS_GRAPH_BASE,
        "transport": "http",
        "auth_type": "oauth2",
        "config_json": {},
        "capabilities_json": [
            "get_availability",
            "list_bookings",
            "schedule_meeting",
            "cancel_meeting",
            "send_microsoft_email",
        ],
        "priority": 75,
    }
