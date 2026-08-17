"""
apollo.py - Apollo.io provider adapter.

Thin wrapper that delegates to the existing apollo_oauth.py token store
and exposes the canonical server config for bootstrapping.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session


def get_token(session: Session, company_id: int) -> Optional[str]:
    from routes.apollo_oauth import get_company_apollo_token
    return get_company_apollo_token(session, company_id)


def build_server_config() -> dict:
    """Return the default MCPServer config dict for Apollo."""
    return {
        "name": "apollo_main",
        "provider": "apollo",
        "url": "https://mcp.apollo.io/mcp",
        "transport": "http",
        "auth_type": "oauth2",
        "capabilities_json": [
            "search_prospects",
            "enrich_prospect",
            "enroll_sequence",
            "outreach_analytics",
        ],
        "priority": 100,
    }
