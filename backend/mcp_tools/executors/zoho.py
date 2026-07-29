from __future__ import annotations

import asyncio
import logging
import os

import httpx

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_ZOHO_API_BASE = os.getenv("ZOHO_API_BASE", "https://www.zohoapis.com/crm/v7")
_ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"


def _get_zoho_token(session: Session, company_id: int) -> str:
    from routes.zoho_oauth import get_company_zoho_token
    token = get_company_zoho_token(session, company_id)
    if not token:
        raise ValueError("Zoho CRM is not connected. Connect at Settings > Integrations > Zoho CRM.")
    return token


def _zoho_headers(token: str) -> dict:
    return {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}


async def _refresh_if_needed(company_id: int, exc: Exception) -> str | None:
    """Attempt a token refresh if the error looks like a 401. Returns new token or None."""
    if "401" not in str(exc):
        return None
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    def _sync_refresh() -> str | None:
        token_val = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                from routes.zoho_oauth import _get_token, _save_token
                refresh_token = _get_token(session, company_id, "refresh_token")
                if not refresh_token:
                    return None
            import httpx as _httpx
            resp = _httpx.post(
                _ZOHO_TOKEN_URL,
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


async def zoho_get_pipeline(company_id: int, limit: int = 50) -> dict:
    def _load_token() -> str:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return _get_zoho_token(session, company_id)
        finally:
            rls_company_id.reset(tok)

    async def _fetch(token: str) -> list[dict]:
        url = f"{_ZOHO_API_BASE}/Deals"
        params = {
            "fields": "Deal_Name,Stage,Amount,Account_Name,Closing_Date",
            "per_page": min(limit, 200),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=_zoho_headers(token), params=params)
            resp.raise_for_status()
            raw = resp.json().get("data", [])
        return [
            {
                "deal_id": d.get("id"),
                "deal_name": d.get("Deal_Name"),
                "stage": d.get("Stage"),
                "amount": d.get("Amount"),
                "account_name": d.get("Account_Name"),
                "closing_date": d.get("Closing_Date"),
            }
            for d in raw
        ]

    try:
        token = await asyncio.to_thread(_load_token)
        deals = await _fetch(token)
        return ToolResult.ok(deals).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                deals = await _fetch(new_token)
                return ToolResult.ok(deals).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:zoho_get_pipeline] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Zoho pipeline fetch failed: {exc}",
            next_suggestion="Check Zoho connection at Settings > Integrations > Zoho CRM.",
        ).model_dump()


async def zoho_create_deal(
    company_id: int,
    deal_name: str,
    stage: str,
    amount: float,
    account_name: str = "",
    closing_date: str = "",
) -> dict:
    def _load_token() -> str:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return _get_zoho_token(session, company_id)
        finally:
            rls_company_id.reset(tok)

    async def _create(token: str) -> dict:
        url = f"{_ZOHO_API_BASE}/Deals"
        payload: dict = {"Deal_Name": deal_name, "Stage": stage, "Amount": amount}
        if account_name:
            payload["Account_Name"] = account_name
        if closing_date:
            payload["Closing_Date"] = closing_date
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                headers=_zoho_headers(token),
                json={"data": [payload]},
            )
            resp.raise_for_status()
            created = resp.json().get("data", [{}])[0]
        deal_id = created.get("details", {}).get("id") or created.get("id", "")
        return {
            "deal_id": deal_id,
            "deal_name": deal_name,
            "stage": stage,
            "zoho_record_url": f"https://crm.zoho.com/crm/org/tab/Potentials/{deal_id}" if deal_id else "",
        }

    try:
        token = await asyncio.to_thread(_load_token)
        data = await _create(token)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                data = await _create(new_token)
                return ToolResult.ok(data).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:zoho_create_deal] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Zoho deal creation failed: {exc}",
            next_suggestion="Verify Zoho connection and that Stage matches a valid pipeline stage.",
        ).model_dump()


async def zoho_update_contact(
    company_id: int,
    contact_id: str,
    phone: str = "",
    email: str = "",
    title: str = "",
    extra_fields: dict | None = None,
) -> dict:
    def _load_token() -> str:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return _get_zoho_token(session, company_id)
        finally:
            rls_company_id.reset(tok)

    async def _update(token: str) -> dict:
        url = f"{_ZOHO_API_BASE}/Contacts/{contact_id}"
        payload: dict = {}
        if phone:
            payload["Phone"] = phone
        if email:
            payload["Email"] = email
        if title:
            payload["Title"] = title
        if extra_fields:
            payload.update(extra_fields)
        if not payload:
            raise ValueError("No fields provided to update.")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.put(
                url,
                headers=_zoho_headers(token),
                json={"data": [payload]},
            )
            resp.raise_for_status()
        return {
            "contact_id": contact_id,
            "updated_fields": list(payload.keys()),
            "zoho_record_url": f"https://crm.zoho.com/crm/org/tab/Contacts/{contact_id}",
        }

    try:
        token = await asyncio.to_thread(_load_token)
        data = await _update(token)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                data = await _update(new_token)
                return ToolResult.ok(data).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:zoho_update_contact] company=%s contact=%s error=%s", company_id, contact_id, exc)
        return ToolResult.fail(
            f"Zoho contact update failed: {exc}",
            next_suggestion="Verify the contact_id exists in Zoho CRM.",
        ).model_dump()
