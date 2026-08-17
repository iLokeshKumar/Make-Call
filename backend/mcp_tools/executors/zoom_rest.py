"""
zoom_rest.py - Zoom REST executors for meeting creation.

The Zoom Meetings MCP server only exposes read-only tools (search, assets,
recordings). Creating meetings goes through the Zoom REST API
(POST /v2/users/me/meetings) with the same stored OAuth token. Used as the
auto-fallback meeting-link provider when Google Calendar is not connected.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_ZOOM_API_BASE = "https://api.zoom.us/v2"


def _get_zoom_token(session: Session, company_id: int) -> str:
    from services.mcp.provider_adapters.zoom import get_token
    token = get_token(session, company_id)
    if not token:
        raise ValueError("Zoom is not connected. Connect at Settings > Integrations > Zoom.")
    return token


def _iso_to_zoom(dt_str: str) -> str:
    """Normalize an ISO-ish datetime to Zoom's UTC start_time format."""
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
    """Attempt a Zoom token refresh if the error looks like a 401. Returns new token or None."""
    if "401" not in str(exc):
        return None

    def _sync_refresh() -> str | None:
        token_val = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                from routes.zoom_oauth import _get, _save, refresh_token as _zoom_refresh
                try:
                    tokens = asyncio.run(_zoom_refresh(session, company_id))
                except Exception:
                    tokens = {}
                new_token = (tokens or {}).get("access_token")
                if new_token:
                    _save(session, company_id, "access_token", new_token)
                    if (tokens or {}).get("refresh_token"):
                        _save(session, company_id, "refresh_token", tokens["refresh_token"])
                return new_token
        finally:
            rls_company_id.reset(token_val)

    return await asyncio.to_thread(_sync_refresh)


def _load_token(company_id: int) -> str:
    tok = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return _get_zoom_token(session, company_id)
    finally:
        rls_company_id.reset(tok)


def _meeting_write_scope_error() -> dict:
    # Lazy import to avoid a circular import (routes.zoom_oauth imports services,
    # and this executor is imported by the tool registry). Keeps the Settings-UI
    # hint and the runtime agent error in lockstep.
    from routes.zoom_oauth import MEETING_WRITE_HINT
    return ToolResult.fail(
        "Zoom meeting creation requires the 'meeting:write' scope, which this app's token does not have.",
        next_suggestion=MEETING_WRITE_HINT,
    ).model_dump()


async def zoom_create_meeting(
    company_id: int,
    topic: str = "Meeting",
    start_time: str = "",
    duration_minutes: int = 30,
    attendee_email: str = "",
    settings: dict | None = None,
) -> dict:
    """Create a Zoom meeting via REST. Returns the join URL on success."""
    topic = (topic or "Meeting").strip()

    def _create(token: str) -> dict:
        payload: dict = {
            "topic": topic,
            "type": 2,  # scheduled meeting
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": True,
                "auto_recording": "none",
            },
        }
        if start_time:
            payload["start_time"] = _iso_to_zoom(start_time)
        payload["duration"] = max(int(duration_minutes or 30), 5)
        if settings:
            payload["settings"].update(settings or {})

        resp = httpx.post(
            f"{_ZOOM_API_BASE}/users/me/meetings",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=25,
        )
        if resp.status_code in (401, 403):
            body = resp.text.lower()
            if "scope" in body or "permission" in body:
                raise PermissionError("zoom_meeting:write_scope_missing")
        resp.raise_for_status()
        created = resp.json()
        return {
            "meeting_id": created.get("id"),
            "topic": created.get("topic"),
            "join_url": created.get("join_url", ""),
            "start_url": created.get("start_url", ""),
            "start_time": created.get("start_time", ""),
            "duration": created.get("duration"),
            "provider": "zoom",
        }

    try:
        token = await asyncio.to_thread(_load_token, company_id)
        return ToolResult.ok(await asyncio.to_thread(_create, token)).model_dump()
    except PermissionError as exc:
        logger.warning("[MCP:zoom_create_meeting] company=%s missing meeting:write scope", company_id)
        return _meeting_write_scope_error()
    except Exception as exc:
        new_token = await _refresh_if_needed(company_id, exc)
        if new_token:
            try:
                return ToolResult.ok(await asyncio.to_thread(_create, new_token)).model_dump()
            except PermissionError:
                return _meeting_write_scope_error()
            except Exception as exc2:
                exc = exc2
        logger.error("[MCP:zoom_create_meeting] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Zoom meeting creation failed: {exc}",
            next_suggestion=(
                "Verify Zoom is connected and 'meeting:write' scope is granted — "
                "add it in the Zoom Marketplace and reconnect."
            ),
        ).model_dump()
