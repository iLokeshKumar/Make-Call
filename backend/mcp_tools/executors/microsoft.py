"""
microsoft.py - Microsoft 365 (Graph) REST executors for scheduling + email.

Microsoft connects via OAuth (routes/microsoft_oauth.py) and has no MCPServer
row, so scheduling capabilities (get_availability, list_bookings,
schedule_meeting, cancel_meeting) and email (send_microsoft_email) are served
directly from the Microsoft Graph API. Token-refresh-on-401 mirrors the Zoho
executor pattern.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _get_ms_token(session: Session, company_id: int) -> str:
    from services.mcp.provider_adapters.microsoft import get_token
    token = get_token(session, company_id)
    if not token:
        raise ValueError("Microsoft 365 is not connected. Connect at Settings > Integrations > Microsoft 365.")
    return token


def _ms_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _iso_to_graph(dt_str: str) -> str:
    """Normalize an ISO-ish datetime to the Graph OData format, ensuring UTC."""
    if not dt_str:
        return dt_str
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return dt_str


async def _refresh_if_needed(company_id: int, exc: Exception) -> str | None:
    """Attempt a token refresh if the error looks like a 401. Returns new token or None."""
    if "401" not in str(exc):
        return None
    client_id = os.getenv("MICROSOFT_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    def _sync_refresh() -> str | None:
        token_val = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                from routes.microsoft_oauth import _get_token, _save_token
                refresh_token = _get_token(session, company_id, "refresh_token")
                if not refresh_token:
                    return None
            import httpx as _httpx
            resp = _httpx.post(
                _MS_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "offline_access Calendars.ReadWrite Mail.Send",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            new_token = data.get("access_token")
            if new_token:
                with Session(engine) as session:
                    _save_token(session, company_id, "access_token", new_token)
                    if data.get("refresh_token"):
                        _save_token(session, company_id, "refresh_token", data["refresh_token"])
            return new_token
        finally:
            rls_company_id.reset(token_val)

    return await asyncio.to_thread(_sync_refresh)


def _load_token(company_id: int) -> str:
    tok = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return _get_ms_token(session, company_id)
    finally:
        rls_company_id.reset(tok)


async def ms_get_availability(
    company_id: int,
    date: str = "",
    start_time: str = "",
    end_time: str = "",
    timezone_id: str = "UTC",
) -> dict:
    """Check availability on the user's Microsoft calendar for a given date."""
    def _fetch(token: str) -> dict:
        # getSchedule requires a non-empty `schedules` array of mailbox addresses,
        # so resolve the signed-in user's own principal first.
        me = httpx.get(
            f"{_MS_GRAPH_BASE}/me",
            headers=_ms_headers(token),
            params={"$select": "mail,userPrincipalName"},
            timeout=15,
        )
        me.raise_for_status()
        me_data = me.json()
        user_principal = me_data.get("mail") or me_data.get("userPrincipalName")
        if not user_principal:
            raise ValueError("Could not resolve the Microsoft 365 user's mailbox address.")

        # Build a day window when only a date is given.
        start = start_time or f"{date}T00:00:00"
        end = end_time or f"{date}T23:59:59"
        payload = {
            "schedules": [user_principal],
            "startTime": {"dateTime": _iso_to_graph(start), "timeZone": timezone_id},
            "endTime": {"dateTime": _iso_to_graph(end), "timeZone": timezone_id},
            "availabilityViewInterval": 30,
        }
        resp = httpx.post(
            f"{_MS_GRAPH_BASE}/me/calendar/getSchedule",
            headers=_ms_headers(token),
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        schedules = resp.json().get("value", [])
        return {"schedules": schedules}

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
        logger.error("[MCP:ms_get_availability] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Microsoft availability check failed: {exc}",
            next_suggestion="Verify Microsoft 365 is connected at Settings > Integrations > Microsoft 365.",
        ).model_dump()


async def ms_list_events(
    company_id: int,
    from_date: str = "",
    to_date: str = "",
    status: str = "",
    limit: int = 25,
) -> dict:
    """List events from the user's Microsoft calendar."""
    def _fetch(token: str) -> dict:
        params: dict = {
            "$top": min(max(limit, 1), 100),
            "$select": "id,subject,start,end,onlineMeeting,isOrganizer,attendees",
            "$orderby": "start/dateTime",
        }
        filters: list[str] = []
        if from_date:
            filters.append(f"start/dateTime ge '{_iso_to_graph(from_date)}'")
        if to_date:
            filters.append(f"end/dateTime le '{_iso_to_graph(to_date)}'")
        if filters:
            params["$filter"] = " and ".join(filters)
        resp = httpx.get(
            f"{_MS_GRAPH_BASE}/me/events",
            headers=_ms_headers(token),
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        events = resp.json().get("value", [])
        return {
            "count": len(events),
            "events": [
                {
                    "event_id": e.get("id"),
                    "subject": e.get("subject"),
                    "start": (e.get("start") or {}).get("dateTime"),
                    "end": (e.get("end") or {}).get("dateTime"),
                    "online_meeting_url": ((e.get("onlineMeeting") or {}).get("joinUrl") or ""),
                    "attendees": [
                        (a.get("emailAddress") or {}).get("address") for a in (e.get("attendees") or [])
                    ],
                }
                for e in events
            ],
        }

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
        logger.error("[MCP:ms_list_events] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Microsoft calendar list failed: {exc}",
            next_suggestion="Verify Microsoft 365 is connected.",
        ).model_dump()


async def ms_create_event(
    company_id: int,
    subject: str,
    start_time: str,
    end_time: str = "",
    invitee_email: str = "",
    invitee_name: str = "",
    notes: str = "",
    create_online_meeting: bool = True,
) -> dict:
    """Create an event on the user's Microsoft calendar (with Teams link option)."""
    if not subject or not start_time:
        return ToolResult.fail(
            "subject and start_time are required.",
            next_suggestion="Pass subject='Demo call' and start_time as ISO 8601.",
        ).model_dump()

    def _create(token: str) -> dict:
        body: dict = {
            "subject": subject,
            "start": {"dateTime": _iso_to_graph(start_time), "timeZone": "UTC"},
            "end": {"dateTime": _iso_to_graph(end_time or start_time), "timeZone": "UTC"},
            "isOnlineMeeting": bool(create_online_meeting),
            "onlineMeetingProvider": "teamsForBusiness" if create_online_meeting else None,
        }
        if invitee_email:
            body["attendees"] = [{
                "emailAddress": {"address": invitee_email, "name": invitee_name or ""},
                "type": "required",
            }]
        if notes:
            body["body"] = {"contentType": "text", "content": notes}
        resp = httpx.post(
            f"{_MS_GRAPH_BASE}/me/events",
            headers=_ms_headers(token),
            json={k: v for k, v in body.items() if v is not None},
            timeout=20,
        )
        resp.raise_for_status()
        created = resp.json()
        return {
            "event_id": created.get("id"),
            "subject": created.get("subject"),
            "start": (created.get("start") or {}).get("dateTime"),
            "online_meeting_url": ((created.get("onlineMeeting") or {}).get("joinUrl") or ""),
            "calendar_link": f"https://outlook.office.com/calendar/item/{quote(str(created.get('id', '')), safe='')}",
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
        logger.error("[MCP:ms_create_event] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Microsoft calendar event creation failed: {exc}",
            next_suggestion="Verify Microsoft 365 is connected and start_time is ISO 8601.",
        ).model_dump()


async def ms_update_event(
    company_id: int,
    event_id: str,
    start_time: str = "",
    end_time: str = "",
    subject: str = "",
    notes: str = "",
) -> dict:
    """Update an existing event on the user's Microsoft calendar (reschedule)."""
    if not event_id:
        return ToolResult.fail("event_id is required.").model_dump()

    def _update(token: str) -> dict:
        body: dict = {}
        if start_time:
            body["start"] = {"dateTime": _iso_to_graph(start_time), "timeZone": "UTC"}
        if end_time:
            body["end"] = {"dateTime": _iso_to_graph(end_time), "timeZone": "UTC"}
        if subject:
            body["subject"] = subject
        if notes:
            body["body"] = {"contentType": "text", "content": notes}
        if not body:
            raise ValueError("No fields provided to update.")
        resp = httpx.patch(
            f"{_MS_GRAPH_BASE}/me/events/{quote(event_id, safe='')}",
            headers=_ms_headers(token),
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        updated = resp.json()
        return {
            "event_id": updated.get("id"),
            "start": (updated.get("start") or {}).get("dateTime"),
            "updated_fields": list(body.keys()),
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
        logger.error("[MCP:ms_update_event] company=%s event=%s error=%s", company_id, event_id, exc)
        return ToolResult.fail(
            f"Microsoft calendar event update failed: {exc}",
            next_suggestion="Verify the event_id is valid in the user's Microsoft calendar.",
        ).model_dump()


async def ms_cancel_event(
    company_id: int,
    event_id: str,
    reason: str = "",
) -> dict:
    """Cancel/delete an event from the user's Microsoft calendar."""
    if not event_id:
        return ToolResult.fail("event_id is required.").model_dump()

    def _cancel(token: str) -> dict:
        headers = _ms_headers(token)
        if reason:
            body = {"comment": reason, "sendResponse": "true"}
            resp = httpx.post(
                f"{_MS_GRAPH_BASE}/me/events/{quote(event_id, safe='')}/cancel",
                headers=headers,
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
        else:
            resp = httpx.delete(
                f"{_MS_GRAPH_BASE}/me/events/{quote(event_id, safe='')}",
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
        return {"event_id": event_id, "cancelled": True}

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_cancel, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_cancel, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:ms_cancel_event] company=%s event=%s error=%s", company_id, event_id, exc)
        return ToolResult.fail(
            f"Microsoft calendar event cancellation failed: {exc}",
            next_suggestion="Verify the event_id is valid in the user's Microsoft calendar.",
        ).model_dump()


async def ms_send_email(
    company_id: int,
    to_email: str,
    subject: str,
    body: str = "",
    cc_email: str = "",
) -> dict:
    """Send an email from the connected Microsoft 365 mailbox (Graph sendMail)."""
    if not to_email or not subject:
        return ToolResult.fail(
            "to_email and subject are required.",
            next_suggestion="Pass to_email='person@company.com' and a subject.",
        ).model_dump()

    def _send(token: str) -> dict:
        message: dict = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body or ""},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
        if cc_email:
            message["ccRecipients"] = [{"emailAddress": {"address": cc_email}}]
        resp = httpx.post(
            f"{_MS_GRAPH_BASE}/me/sendMail",
            headers=_ms_headers(token),
            json={"message": message, "saveToSentItems": True},
            timeout=20,
        )
        resp.raise_for_status()
        return {"sent": True, "to": to_email, "subject": subject}

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_send, token)).model_dump()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_send, new_token)).model_dump()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:ms_send_email] company=%s to=%s error=%s", company_id, to_email, exc)
        return ToolResult.fail(
            f"Microsoft email send failed: {exc}",
            next_suggestion="Verify Microsoft 365 is connected and Mail.Send scope is granted.",
        ).model_dump()
