"""
hubspot.py - HubSpot REST executors for CRM capabilities.

HubSpot connects via OAuth (routes/hubspot_oauth.py) and has no MCPServer row,
so capabilities (search_prospects, create/update_crm_contact, crm_query) are
served directly from the HubSpot REST API. Token-refresh-on-401 mirrors the
Zoho executor pattern.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_HUBSPOT_API_BASE = "https://api.hubapi.com"
_HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"


def _get_hubspot_token(session: Session, company_id: int) -> str:
    from services.mcp.provider_adapters.hubspot import get_token
    token = get_token(session, company_id)
    if not token:
        raise ValueError("HubSpot is not connected. Connect at Settings > Integrations > HubSpot.")
    return token


def _hubspot_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _refresh_if_needed(company_id: int, exc: Exception) -> str | None:
    """Attempt a token refresh if the error looks like a 401. Returns new token or None."""
    if "401" not in str(exc):
        return None
    client_id = os.getenv("HUBSPOT_CLIENT_ID")
    client_secret = os.getenv("HUBSPOT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    def _sync_refresh() -> str | None:
        token_val = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                from routes.hubspot_oauth import _get_token, _save_token
                refresh_token = _get_token(session, company_id, "refresh_token")
                if not refresh_token:
                    return None
            import httpx as _httpx
            resp = _httpx.post(
                _HUBSPOT_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
            resp.raise_for_status()
            new_token = resp.json().get("access_token")
            if new_token:
                with Session(engine) as session:
                    _save_token(session, company_id, "access_token", new_token)
            return new_token
        finally:
            rls_company_id.reset(token_val)

    return await asyncio.to_thread(_sync_refresh)


def _load_token(company_id: int) -> str:
    tok = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return _get_hubspot_token(session, company_id)
    finally:
        rls_company_id.reset(tok)


async def hubspot_search_contacts(
    company_id: int,
    query: str = "",
    person_title: str = "",
    company: str = "",
    location: str = "",
    limit: int = 10,
) -> dict:
    """Search HubSpot contacts. Mirrors the search_prospects capability shape."""
    def _search(token: str) -> dict:
        body: dict = {"limit": min(limit, 100)}
        if query:
            body["query"] = query
        if person_title or company or location:
            filters: list[dict] = []
            if person_title:
                filters.append({"propertyName": "jobtitle", "operator": "CONTAINS_TOKEN", "value": person_title})
            if company:
                filters.append({"propertyName": "company", "operator": "CONTAINS_TOKEN", "value": company})
            if location:
                filters.append({"propertyName": "city", "operator": "CONTAINS_TOKEN", "value": location})
            body["filterGroups"] = [{"filters": filters}]
        resp = httpx.post(
            f"{_HUBSPOT_API_BASE}/crm/v3/objects/contacts/search",
            headers=_hubspot_headers(token),
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return {
            "count": len(results),
            "contacts": [
                {
                    "contact_id": c.get("id"),
                    "name": (c.get("properties") or {}).get("firstname", "") + " " + (c.get("properties") or {}).get("lastname", ""),
                    "email": (c.get("properties") or {}).get("email", ""),
                    "phone": (c.get("properties") or {}).get("phone", ""),
                    "company": (c.get("properties") or {}).get("company", ""),
                    "jobtitle": (c.get("properties") or {}).get("jobtitle", ""),
                    "city": (c.get("properties") or {}).get("city", ""),
                }
                for c in results
            ],
        }

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_search, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_search, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:hubspot_search_contacts] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"HubSpot contact search failed: {exc}",
            next_suggestion="Check HubSpot connection at Settings > Integrations > HubSpot.",
        ).model_dump()


async def hubspot_create_contact(
    company_id: int,
    name: str = "",
    email: str = "",
    phone: str = "",
    company: str = "",
    title: str = "",
    description: str = "",
) -> dict:
    """Create a Contact in HubSpot via REST (fallback for create_crm_contact)."""
    name = (name or "").strip()
    if not name:
        return ToolResult.fail(
            "A contact name is required.",
            next_suggestion="Pass name='John Doe'.",
        ).model_dump()
    first, _, last = name.partition(" ")
    properties: dict = {
        "firstname": first.strip(),
        "lastname": (last.strip() or first.strip()) if not last.strip() else last.strip(),
    }
    if email:
        properties["email"] = email
    if phone:
        properties["phone"] = phone
    if company:
        properties["company"] = company
    if title:
        properties["jobtitle"] = title
    if description:
        properties["notes_last_contacted_outreach"] = description

    def _create(token: str) -> dict:
        resp = httpx.post(
            f"{_HUBSPOT_API_BASE}/crm/v3/objects/contacts",
            headers=_hubspot_headers(token),
            json={"properties": properties},
            timeout=20,
        )
        resp.raise_for_status()
        created = resp.json()
        contact_id = created.get("id", "")
        return {
            "contact_id": contact_id,
            "name": name,
            "hubspot_record_url": f"https://app.hubspot.com/contacts/{contact_id}" if contact_id else "",
        }

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_create, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_create, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:hubspot_create_contact] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"HubSpot contact creation failed: {exc}",
            next_suggestion="Verify HubSpot is connected at Settings > Integrations > HubSpot.",
        ).model_dump()


async def hubspot_update_contact(
    company_id: int,
    contact_id: str,
    data: dict | None = None,
) -> dict:
    """Update a HubSpot contact by id via REST (fallback for update_crm_contact)."""
    data = data or {}

    def _update(token: str) -> dict:
        resp = httpx.patch(
            f"{_HUBSPOT_API_BASE}/crm/v3/objects/contacts/{contact_id}",
            headers=_hubspot_headers(token),
            json={"properties": data},
            timeout=20,
        )
        resp.raise_for_status()
        return {
            "contact_id": contact_id,
            "updated_fields": list(data.keys()),
            "hubspot_record_url": f"https://app.hubspot.com/contacts/{contact_id}",
        }

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_update, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_update, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:hubspot_update_contact] company=%s contact=%s error=%s", company_id, contact_id, exc)
        return ToolResult.fail(
            f"HubSpot contact update failed: {exc}",
            next_suggestion="Verify the contact_id exists in HubSpot.",
        ).model_dump()


async def hubspot_query_records(
    company_id: int,
    object_type: str = "contacts",
    query: str = "",
    limit: int = 25,
) -> dict:
    """Query HubSpot CRM objects (contacts/companies/deals) via search API."""
    object_type = (object_type or "contacts").strip().lower()
    if object_type not in ("contacts", "companies", "deals"):
        return ToolResult.fail(
            f"Unsupported HubSpot object '{object_type}'.",
            next_suggestion="Use one of: contacts, companies, deals.",
        ).model_dump()

    def _fetch(token: str) -> dict:
        body: dict = {"limit": min(max(limit, 1), 100)}
        if query.strip():
            body["query"] = query.strip()
        resp = httpx.post(
            f"{_HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/search",
            headers=_hubspot_headers(token),
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return {"object_type": object_type, "count": len(results), "records": results[:100]}

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_fetch, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_fetch, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:hubspot_query_records] company=%s object=%s error=%s", company_id, object_type, exc)
        return ToolResult.fail(
            f"HubSpot query failed: {exc}",
            next_suggestion="Verify HubSpot is connected and the object type is valid.",
        ).model_dump()
