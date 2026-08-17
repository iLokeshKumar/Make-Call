from __future__ import annotations

import asyncio
import logging
import os
import secrets

from database import engine, rls_company_id
from models.models import Lead
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_GCAL_CLIENT_ID = os.getenv("GCAL_CLIENT_ID", "")
_GCAL_CLIENT_SECRET = os.getenv("GCAL_CLIENT_SECRET", "")
_GCAL_REDIRECT_URI = os.getenv("GCAL_REDIRECT_URI", "")
_PKCE_CACHE: dict[int, str] = {}

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


async def get_google_auth_url(company_id: int) -> dict:
    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore[import]
    except ImportError:
        return ToolResult.fail(
            "google-auth-oauthlib is not installed.",
            next_suggestion="Run: pip install google-auth-oauthlib",
        ).model_dump()

    try:
        code_verifier = secrets.token_urlsafe(64)
        _PKCE_CACHE[company_id] = code_verifier

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": _GCAL_CLIENT_ID,
                    "client_secret": _GCAL_CLIENT_SECRET,
                    "redirect_uris": [_GCAL_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=CALENDAR_SCOPES,
        )
        flow.redirect_uri = _GCAL_REDIRECT_URI
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=str(company_id),
        )
        return ToolResult.ok({"auth_url": auth_url}).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_google_auth_url] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Failed to generate Google auth URL: {exc}",
            next_suggestion="Check GCAL_CLIENT_ID and GCAL_REDIRECT_URI environment variables.",
        ).model_dump()


async def submit_google_auth_code(company_id: int, code: str) -> dict:
    from routes.calendar import _save_setting

    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore[import]
        from googleapiclient.discovery import build  # type: ignore[import]
    except ImportError:
        return ToolResult.fail(
            "google-auth-oauthlib / google-api-python-client not installed.",
            next_suggestion="Run: pip install google-auth-oauthlib google-api-python-client",
        ).model_dump()

    def _sync() -> dict:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": _GCAL_CLIENT_ID,
                    "client_secret": _GCAL_CLIENT_SECRET,
                    "redirect_uris": [_GCAL_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=CALENDAR_SCOPES,
        )
        flow.redirect_uri = _GCAL_REDIRECT_URI
        flow.fetch_token(code=code)
        creds = flow.credentials

        service = build("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()
        email = user_info.get("email", "")

        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                _save_setting(session, company_id, "GCAL_ACCESS_TOKEN", creds.token)
                _save_setting(session, company_id, "GCAL_REFRESH_TOKEN", creds.refresh_token or "")
                _save_setting(session, company_id, "GCAL_EMAIL", email, is_secret=False)
        finally:
            rls_company_id.reset(token)

        return {"connected": True, "email": email}

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:submit_google_auth_code] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Google auth exchange failed: {exc}",
            next_suggestion="The auth code may have expired. Call get_google_auth_url to start a new flow.",
        ).model_dump()


async def book_meeting(
    company_id: int,
    lead_email: str,
    lead_name: str,
    scheduled_at: str,
    duration_minutes: int = 30,
    title: str = "Follow-up Call",
    description: str = "",
) -> dict:
    return await _book_calendar_event(
        company_id=company_id,
        lead_email=lead_email,
        lead_name=lead_name,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        title=title,
        description=description,
    )


async def book_demo(
    company_id: int,
    lead_email: str,
    lead_name: str,
    scheduled_at: str,
    duration_minutes: int = 45,
    product_name: str = "",
) -> dict:
    title = f"Product Demo{': ' + product_name if product_name else ''}"
    description = f"Product demonstration for {lead_name}."
    return await _book_calendar_event(
        company_id=company_id,
        lead_email=lead_email,
        lead_name=lead_name,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        title=title,
        description=description,
    )


async def schedule_demo(
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    requested_time: str,
    product: str,
    demo_type: str = "Online",
    duration_minutes: int = 30,
    notes: str | None = None,
    provider: str | None = None,
) -> dict:
    """Canonical MCP scheduling entry point.

    The domain service owns lead lookup, timezone resolution, persistence,
    calendar/Meet creation, email delivery, and the returned truth.
    """
    from services.agent.agent_tool_service import book_demo as domain_schedule_demo

    token = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            lead = session.get(Lead, lead_id)
            if not lead or lead.company_id != company_id:
                return ToolResult.fail(f"Lead {lead_id} was not found in this company.").model_dump()
            return await domain_schedule_demo(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                name=lead.name or "",
                phone=lead.normalized_phone or "",
                demo_date=requested_time,
                products=product,
                demo_type=demo_type,
                duration_minutes=duration_minutes,
                email=lead.email,
                notes=notes,
                provider=provider,
            )
    except ValueError as exc:
        return ToolResult.fail(str(exc), next_suggestion="Ask the lead to confirm the date and time again.").model_dump()
    finally:
        rls_company_id.reset(token)


async def _book_calendar_event(
    company_id: int,
    lead_email: str,
    lead_name: str,
    scheduled_at: str,
    duration_minutes: int,
    title: str,
    description: str,
) -> dict:
    from datetime import datetime, timedelta, timezone
    from routes.calendar import _get_setting

    try:
        from google.oauth2.credentials import Credentials  # type: ignore[import]
        from googleapiclient.discovery import build  # type: ignore[import]
    except ImportError:
        return ToolResult.fail(
            "google-api-python-client not installed.",
            next_suggestion="Run: pip install google-api-python-client google-auth",
        ).model_dump()

    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                access_token = _get_setting(session, company_id, "GCAL_ACCESS_TOKEN")
                refresh_token = _get_setting(session, company_id, "GCAL_REFRESH_TOKEN")
                host_email = _get_setting(session, company_id, "GCAL_EMAIL")
            if not access_token:
                raise ValueError("Google Calendar not connected. Call get_google_auth_url first.")
        finally:
            rls_company_id.reset(token)

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=_GCAL_CLIENT_ID,
            client_secret=_GCAL_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        service = build("calendar", "v3", credentials=creds)

        start_dt = datetime.fromisoformat(scheduled_at).astimezone(timezone.utc)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "attendees": [
                {"email": lead_email, "displayName": lead_name},
                {"email": host_email or "", "self": True},
            ],
            "conferenceData": {
                "createRequest": {"requestId": secrets.token_hex(8), "conferenceSolutionKey": {"type": "hangoutsMeet"}},
            },
        }
        created = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        meet_link = ""
        if created.get("conferenceData", {}).get("entryPoints"):
            for ep in created["conferenceData"]["entryPoints"]:
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri", "")
                    break

        return {
            "event_id": created["id"],
            "calendar_link": created.get("htmlLink", ""),
            "meet_link": meet_link,
            "scheduled_at": scheduled_at,
            "attendees": [lead_email, host_email],
        }

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:book_calendar_event] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Calendar booking failed: {exc}",
            next_suggestion="Check that Google Calendar is connected and scheduled_at is ISO 8601 format.",
        ).model_dump()
