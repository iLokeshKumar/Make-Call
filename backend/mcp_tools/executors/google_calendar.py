"""
google_calendar.py - Google Calendar executors for scheduling capabilities.

Used as the LAST fallback provider in the scheduling capability chain (after
Cal.com → Calendly → Microsoft 365). When the company has Google Calendar
connected (GCAL_* tokens), schedule_meeting / get_availability /
list_bookings / reschedule_meeting / cancel_meeting can be served here.
Events are created with a Google Meet link via conferenceData.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)


def _load_creds_and_service(company_id: int):
    from routes.calendar import get_company_calendar_credentials

    def _load() -> tuple:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                creds = get_company_calendar_credentials(session, company_id)
        finally:
            rls_company_id.reset(tok)
        if not creds:
            raise ValueError(
                "Google Calendar is not connected. Connect at Settings > Integrations > Google Calendar."
            )
        from googleapiclient.discovery import build as _gcal_build
        service = _gcal_build("calendar", "v3", credentials=creds, cache_discovery=False)
        return creds, service

    return _load()


def _iso_to_utc(dt_str: str) -> str:
    if not dt_str:
        return dt_str
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        return dt_str


async def gcal_get_availability(
    company_id: int,
    date: str = "",
    start_time: str = "",
    end_time: str = "",
    timezone_id: str = "UTC",
) -> dict:
    """Return free/busy slots on the primary Google Calendar for a date/window."""
    def _fetch() -> dict:
        _, service = _load_creds_and_service(company_id)
        now = datetime.now(timezone.utc)
        if date and len(date) == 10:
            day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
            start = day
            end = day + timedelta(days=1)
        else:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else now
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00")) if end_time else start + timedelta(hours=8)

        # Primary calendar id — fetch the 'primary' calendar's id for freebusy.
        cal = service.calendars().get(calendarId="primary").execute()
        cal_id = cal.get("id")

        body = {
            "timeMin": start.astimezone(timezone.utc).isoformat(),
            "timeMax": end.astimezone(timezone.utc).isoformat(),
            "items": [{"id": cal_id}],
        }
        resp = service.freebusy().query(body=body).execute()
        busy = resp.get("calendars", {}).get(cal_id, {}).get("busy", [])

        free: list[dict] = []
        cursor = start
        for block in busy:
            b_start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
            b_end = datetime.fromisoformat(block["end"].replace("Z", "+00:00"))
            if b_start > cursor:
                free.append({"start": cursor.isoformat(), "end": b_start.isoformat()})
            cursor = max(cursor, b_end)
        if cursor < end:
            free.append({"start": cursor.isoformat(), "end": end.isoformat()})
        return {"date": date or start_time, "free_slots": free, "busy": busy, "provider": "google_calendar"}

    try:
        return ToolResult.ok(await asyncio.to_thread(_fetch)).model_dump()
    except Exception as exc:
        logger.error("[MCP:gcal_get_availability] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Google Calendar availability check failed: {exc}",
            next_suggestion="Verify Google Calendar is connected at Settings > Integrations > Google Calendar.",
        ).model_dump()


async def gcal_list_events(
    company_id: int,
    from_date: str = "",
    to_date: str = "",
    status: str = "",
    limit: int = 25,
) -> dict:
    """List upcoming events on the primary Google Calendar."""
    def _fetch() -> dict:
        _, service = _load_creds_and_service(company_id)
        params: dict = {
            "calendarId": "primary",
            "maxResults": min(max(limit, 1), 100),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if from_date:
            params["timeMin"] = _iso_to_utc(from_date)
        if to_date:
            params["timeMax"] = _iso_to_utc(to_date)
        events = service.events().list(**params).execute().get("items", [])
        return {
            "count": len(events),
            "events": [
                {
                    "event_id": e.get("id"),
                    "summary": e.get("summary"),
                    "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                    "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                    "meet_link": next(
                        (ep.get("uri") for ep in (e.get("conferenceData") or {}).get("entryPoints", [])
                         if ep.get("entryPointType") == "video"), None),
                }
                for e in events
            ],
            "provider": "google_calendar",
        }

    try:
        return ToolResult.ok(await asyncio.to_thread(_fetch)).model_dump()
    except Exception as exc:
        logger.error("[MCP:gcal_list_events] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Google Calendar event list failed: {exc}",
            next_suggestion="Verify Google Calendar is connected.",
        ).model_dump()


async def gcal_create_event(
    company_id: int,
    subject: str,
    start_time: str,
    end_time: str = "",
    invitee_email: str = "",
    invitee_name: str = "",
    notes: str = "",
    duration_minutes: int = 30,
) -> dict:
    """Create a Google Calendar event with a Google Meet link."""
    if not subject or not start_time:
        return ToolResult.fail(
            "subject and start_time are required.",
            next_suggestion="Pass subject='Demo call' and start_time as ISO 8601.",
        ).model_dump()

    def _create() -> dict:
        _, service = _load_creds_and_service(company_id)
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = (datetime.fromisoformat(end_time.replace("Z", "+00:00")) if end_time
                  else start_dt + timedelta(minutes=duration_minutes))

        event_body: dict = {
            "summary": subject,
            "start": {"dateTime": start_dt.astimezone(timezone.utc).isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.astimezone(timezone.utc).isoformat(), "timeZone": "UTC"},
            "conferenceData": {
                "createRequest": {
                    "requestId": secrets.token_hex(8),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        if invitee_email:
            event_body["attendees"] = [{"email": invitee_email, "displayName": invitee_name or ""}]
        if notes:
            event_body["description"] = notes

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        meet_link = next(
            (ep.get("uri") for ep in (created.get("conferenceData") or {}).get("entryPoints", [])
             if ep.get("entryPointType") == "video"), None)
        return {
            "event_id": created.get("id"),
            "calendar_link": created.get("htmlLink", ""),
            "meet_link": meet_link,
            "start": (created.get("start") or {}).get("dateTime"),
            "provider": "google_calendar",
        }

    try:
        return ToolResult.ok(await asyncio.to_thread(_create)).model_dump()
    except Exception as exc:
        logger.error("[MCP:gcal_create_event] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Google Calendar event creation failed: {exc}",
            next_suggestion="Verify Google Calendar is connected and start_time is ISO 8601.",
        ).model_dump()


async def gcal_reschedule_event(
    company_id: int,
    event_id: str,
    new_start_time: str = "",
    end_time: str = "",
    subject: str = "",
) -> dict:
    """Move an existing Google Calendar event to a new time."""
    if not event_id:
        return ToolResult.fail("event_id is required.").model_dump()

    def _update() -> dict:
        _, service = _load_creds_and_service(company_id)
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        if new_start_time:
            start_dt = datetime.fromisoformat(new_start_time.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            old_start = datetime.fromisoformat((event.get("start") or {}).get("dateTime", "").replace("Z", "+00:00"))
            old_end = datetime.fromisoformat((event.get("end") or {}).get("dateTime", "").replace("Z", "+00:00"))
            duration = old_end - old_start if old_end > old_start else timedelta(minutes=30)
            if end_time:
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            else:
                end_dt = start_dt + duration
            event["start"] = {"dateTime": start_dt.astimezone(timezone.utc).isoformat(), "timeZone": "UTC"}
            event["end"] = {"dateTime": end_dt.astimezone(timezone.utc).isoformat(), "timeZone": "UTC"}
        if subject:
            event["summary"] = subject
        updated = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
        return {
            "event_id": event_id,
            "start": (updated.get("start") or {}).get("dateTime"),
            "provider": "google_calendar",
        }

    try:
        return ToolResult.ok(await asyncio.to_thread(_update)).model_dump()
    except Exception as exc:
        logger.error("[MCP:gcal_reschedule_event] company=%s event=%s error=%s", company_id, event_id, exc)
        return ToolResult.fail(
            f"Google Calendar reschedule failed: {exc}",
            next_suggestion="Verify the event_id exists in the connected Google Calendar.",
        ).model_dump()


async def gcal_cancel_event(
    company_id: int,
    event_id: str,
    reason: str = "",
) -> dict:
    """Cancel (delete) a Google Calendar event."""
    if not event_id:
        return ToolResult.fail("event_id is required.").model_dump()

    def _cancel() -> dict:
        _, service = _load_creds_and_service(company_id)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"event_id": event_id, "cancelled": True, "provider": "google_calendar"}

    try:
        return ToolResult.ok(await asyncio.to_thread(_cancel)).model_dump()
    except Exception as exc:
        logger.error("[MCP:gcal_cancel_event] company=%s event=%s error=%s", company_id, event_id, exc)
        return ToolResult.fail(
            f"Google Calendar cancellation failed: {exc}",
            next_suggestion="Verify the event_id exists in the connected Google Calendar.",
        ).model_dump()
