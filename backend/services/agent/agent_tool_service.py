from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from database import engine
from credentials_service import get_company_setting_value
from models.models import Appointment, Interaction, LatencyLog, Lead, Product, User, utc_now
from services.communication.communication_service import send_email_to_lead, send_whatsapp_to_lead
from utils.phone import normalize_phone
from utils.timezone_utils import (
    format_datetime_for_timezone,
    localize_datetime,
    parse_datetime_for_timezone,
    resolve_lead_timezone,
)

logger = logging.getLogger(__name__)


def _products_overlap(products_a: str, products_b: str) -> bool:
    """Return True if two product strings share a meaningful keyword (>3 chars)."""
    def tokens(s: str) -> set[str]:
        return {w.lower() for w in re.split(r"[\s,;/]+", s or "") if len(w) > 3}
    return bool(tokens(products_a) & tokens(products_b))


def _find_existing_appointment(
    session: Session,
    company_id: int,
    lead_id: int,
    products: str | None = None,
) -> Appointment | None:
    """
    Return an existing SCHEDULED future appointment for this lead.
    If `products` is given, only match if the products overlap.
    Also catches demos booked in the last 2 hours (handles barge-in repeats).
    """
    now = utc_now()
    window_start = now - timedelta(hours=2)

    appts = session.exec(
        select(Appointment).where(
            Appointment.company_id == company_id,
            Appointment.lead_id == lead_id,
            Appointment.status == "scheduled",
            Appointment.appointment_time >= window_start,
        ).order_by(Appointment.appointment_time.asc())
    ).all()

    if not appts:
        return None

    if not products:
        return appts[0]

    for appt in appts:
        notes = appt.notes or ""
        # Extract the products string stored in notes (format: products=X;)
        m = re.search(r"products=([^;]+)", notes, re.IGNORECASE)
        existing_products = m.group(1).strip() if m else ""
        if not existing_products or _products_overlap(products, existing_products):
            return appt

    return None

try:
    from rag_service import sync_products_to_chroma
except Exception:
    sync_products_to_chroma = None

try:
    from utils.date_normalizer import normalize_date_ai
except Exception:
    normalize_date_ai = None


def get_user_or_404(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_lead_or_404(session: Session, company_id: int, lead_id: int) -> Lead:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def meeting_provider_display(provider: str | None, meet_link: str | None) -> str:
    """Return a human-friendly meeting provider label for emails/messages.

    Prefers the explicitly recorded provider (from appointment notes), falling
    back to a link-based inference for legacy bookings.
    """
    key = (provider or "").strip().lower()
    if key in ("google_meet", "google"):
        return "Google Meet"
    if key in ("zoom", "microsoft", "microsoft_teams", "teams", "calcom", "calendly"):
        return {
            "zoom": "Zoom",
            "microsoft": "Microsoft Teams",
            "microsoft_teams": "Microsoft Teams",
            "teams": "Microsoft Teams",
            "calcom": "Cal.com",
            "calendly": "Calendly",
        }[key]
    if meet_link:
        lower = meet_link.lower()
        if "zoom.us" in lower or "zoom.com" in lower:
            return "Zoom"
        if "meet.google.com" in lower or "meet.google" in lower:
            return "Google Meet"
        if "teams.microsoft.com" in lower or "teams.live.com" in lower:
            return "Microsoft Teams"
        if "cal.com" in lower:
            return "Cal.com"
        if "calendly.com" in lower:
            return "Calendly"
    return "online"


def _has_recent_demo_confirmation(
    session: Session,
    *,
    company_id: int,
    lead_id: int,
    content: str,
) -> bool:
    """Detect a second send of the same booking confirmation in one call."""
    if not content:
        return False
    recent_cutoff = utc_now() - timedelta(minutes=10)
    appointment = session.exec(
        select(Appointment)
        .where(
            Appointment.company_id == company_id,
            Appointment.lead_id == lead_id,
            Appointment.status == "scheduled",
            Appointment.created_at >= recent_cutoff,
        )
        .order_by(Appointment.created_at.desc())
    ).first()
    if not appointment or not appointment.meeting_link or appointment.meeting_link not in content:
        return False

    prior = session.exec(
        select(Interaction)
        .where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == "email",
            Interaction.created_at >= recent_cutoff,
        )
        .order_by(Interaction.created_at.desc())
    ).all()
    return any(
        (item.content or "").lower() in {"online demo scheduled", "demo scheduled", "demo confirmation"}
        for item in prior
    )


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def resolve_meeting_time(raw_value: str) -> datetime:
    timezone_str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    if raw_value and "T" in raw_value:
        return parse_datetime_for_timezone(
            raw_value,
            timezone_str,
            require_local_wall_clock=True,
        )
    if normalize_date_ai:
        normalized = await normalize_date_ai(raw_value, timezone_str=timezone_str)
        if normalized:
            return localize_datetime(normalized, timezone_str)
    return localize_datetime(datetime.now(), timezone_str) + timedelta(days=1)


async def resolve_meeting_time_for_lead(
    session: Session,
    company_id: int,
    lead: Lead,
    raw_value: str,
) -> datetime:
    timezone_str = resolve_lead_timezone(lead, session=session, company_id=company_id)
    if raw_value and "T" in raw_value:
        # book_demo's public contract is a lead-local wall-clock time. Do not
        # let an LLM-produced trailing Z turn 10:00 IST into 15:30 IST.
        return parse_datetime_for_timezone(
            raw_value,
            timezone_str,
            require_local_wall_clock=True,
        )
    if normalize_date_ai:
        normalized = await normalize_date_ai(raw_value, timezone_str=timezone_str)
        if normalized:
            return localize_datetime(normalized, timezone_str)
    fallback_local = localize_datetime(datetime.now(), timezone_str) + timedelta(days=1)
    return fallback_local


def check_icp_qualification(
    company_size: str,
    industry: str,
    employee_count: int,
) -> dict[str, Any]:
    qualified_industries = {
        "tech",
        "saas",
        "manufacturing",
        "electronics",
        "healthcare",
        "finance",
        "retail",
        "distribution",
    }
    size_map = {
        "enterprise": (1000, "high"),
        "mid-market": (100, "high"),
        "mid_market": (100, "high"),
        "smb": (10, "medium"),
    }

    normalized_size = (company_size or "").strip().lower()
    normalized_industry = (industry or "").strip().lower()
    reasons: list[str] = []
    qualified = True
    priority = "low"

    if normalized_industry in qualified_industries:
        reasons.append(f"Industry '{industry}' matches target profile.")
    else:
        reasons.append(f"Industry '{industry}' is outside the default ICP.")
        qualified = False

    if normalized_size in size_map:
        minimum, priority = size_map[normalized_size]
        if employee_count < minimum:
            reasons.append(f"Employee count {employee_count} is below the {minimum} minimum for {company_size}.")
            qualified = False
        else:
            reasons.append(f"Company size '{company_size}' is in range.")
    else:
        reasons.append(f"Company size '{company_size}' is unknown.")
        qualified = False

    return {
        "is_qualified": qualified,
        "priority": priority if qualified else "low",
        "reason": " ".join(reasons),
    }


def get_product_info(
    session: Session,
    company_id: int,
    product_name: str,
) -> dict[str, Any]:
    query = f"%{(product_name or '').strip()}%"
    product = session.exec(
        select(Product).where(
            Product.company_id == company_id,
            or_(
                Product.name.ilike(query),
                Product.sku.ilike(query),
                Product.note.ilike(query),
            ),
        ).order_by(Product.stock.desc(), Product.created_at.desc())
    ).first()

    if not product:
        return {
            "error": "Product not found",
            "status": "Unavailable",
            "message": "No matching product was found in this company's catalog.",
        }

    return {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku,
        "price": str(product.price),
        "currency": product.currency,
        "stock": product.stock,
        "note": product.note or "",
        "status": "Available" if product.is_active and product.stock > 0 else "Unavailable",
    }


def check_guardrails(
    requested_discount_percent: float,
    auto_approve_limit: float = 10.0,
) -> dict[str, Any]:
    approved = requested_discount_percent <= auto_approve_limit
    return {
        "approved": approved,
        "max_allowed_discount": auto_approve_limit,
        "requires_manager": not approved,
        "message": (
            f"Discount of {requested_discount_percent}% is within the auto-approved range."
            if approved
            else f"Discount of {requested_discount_percent}% exceeds the auto-approved limit of {auto_approve_limit}%."
        ),
    }


def get_or_create_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    name: str,
    phone: str,
    email: str | None = None,
) -> dict[str, Any]:
    normalized_phone = normalize_phone(phone)
    lead = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.normalized_phone == normalized_phone,
        )
    ).first()

    if not lead and email:
        lead = session.exec(
            select(Lead).where(
                Lead.company_id == company_id,
                Lead.email == email.strip().lower(),
            )
        ).first()

    if lead:
        updated = False
        if email and not lead.email:
            lead.email = email.strip().lower()
            updated = True
        if name and lead.name != name.strip():
            lead.name = name.strip()
            updated = True
        if updated:
            lead.updated_at = utc_now()
            lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
            session.refresh(lead)
        return {
            "lead_id": lead.id,
            "name": lead.name,
            "email": lead.email,
            "phone": lead.normalized_phone,
            "created": False,
            "message": "Existing lead identified.",
        }

    # Never persist a "headless" lead: a caller without a name or phone would
    # create a row that only shows default status chips (New / Unqualified /
    # None) on the pipeline page. Refuse to create and let the agent ask for
    # the missing identity instead. Existing-lead lookup/update above is
    # unaffected (it intentionally tolerates an empty name on update).
    clean_name = (name or "").strip()
    if not clean_name:
        return {
            "error": "The caller's name is required before creating a lead record.",
            "status": "needs_name",
            "next_suggestion": "Ask the caller for their name, then call get_or_create_lead again with the name.",
        }
    if not normalized_phone:
        return {
            "error": "A phone number is required before creating a lead record.",
            "status": "needs_phone",
            "next_suggestion": "Confirm the caller's phone number, then call get_or_create_lead again.",
        }

    lead = Lead(
        company_id=company_id,
        owner_user_id=actor_user_id,
        name=clean_name,
        normalized_phone=normalized_phone,
        email=email.strip().lower() if email else None,
        status="new",
        source="voice_agent",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {
        "lead_id": lead.id,
        "name": lead.name,
        "email": lead.email,
        "phone": lead.normalized_phone,
        "created": True,
        "message": "New lead created.",
    }


def _create_calendar_event_with_meet(
    session: Session,
    company_id: int,
    summary: str,
    description: str,
    start_time: datetime,
    duration_minutes: int = 30,
    attendee_email: str | None = None,
) -> tuple[str | None, str | None]:
    """Create a Google Calendar event with a Google Meet link for a company.

    Returns ``(meet_link, calendar_event_id)`` on success, or ``(None, None)``
    when Google Calendar is not connected or creation fails — never raises.
    This is the single Meet-link creation path shared by book_meeting and
    book_demo (online demos).
    """
    try:
        from routes.calendar import get_company_calendar_credentials
        from googleapiclient.discovery import build as _gcal_build
        import uuid as _uuid

        gcal_creds = get_company_calendar_credentials(session, company_id)
        if not gcal_creds:
            return None, None

        service = _gcal_build("calendar", "v3", credentials=gcal_creds, cache_discovery=False)
        if start_time.tzinfo is None:
            raise ValueError("Calendar booking requires a timezone-aware start time")
        start_utc = start_time.astimezone(timezone.utc)
        end_utc = start_utc + timedelta(minutes=duration_minutes)
        start_iso = start_utc.isoformat()
        end_iso = end_utc.isoformat()
        event_body: dict = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
            "conferenceData": {
                "createRequest": {
                    "requestId": str(_uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        if attendee_email:
            event_body["attendees"] = [{"email": attendee_email}]
        created = service.events().insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()
        meet_link = (
            created.get("conferenceData", {})
            .get("entryPoints", [{}])[0]
            .get("uri")
        )
        return meet_link, created.get("id")
    except Exception as _exc:
        logger.warning("[calendar] Google Meet event creation failed for company %s: %s", company_id, _exc)
        return None, None


async def _create_zoom_meeting_link(
    session: Session,
    company_id: int,
    topic: str,
    start_time: datetime,
    duration_minutes: int = 30,
    attendee_email: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Create a Zoom meeting via the REST API; return ``(join_url, meeting_id, link_hint)``.

    Used as the auto-fallback when Google Calendar is not connected: bookings
    prefer a Google Meet link, then fall back to a Zoom link. ``link_hint``
    explains why no link could be created (e.g. the meeting:write scope hint) so
    callers can surface it in the agent's booking summary. Returns ``(None, None,
    hint)`` when Zoom is not connected or creation fails — never raises.
    """
    generic_failure_hint = "Could not create a Zoom meeting link — the booking was saved without a join link."
    try:
        # Same gate as the create_meeting tool: skip the doomed API call when the
        # stored Zoom scopes definitively lack meeting:write. Unknown (legacy)
        # falls through to the runtime executor, which returns the clear scope
        # error if Zoom rejects the call.
        from routes.zoom_oauth import MEETING_WRITE_HINT, zoom_meeting_write_granted
        if zoom_meeting_write_granted(session, company_id) is False:
            logger.warning(
                "[book_meeting] Zoom fallback skipped for company %s — missing meeting:write scope",
                company_id,
            )
            return None, None, MEETING_WRITE_HINT
    except Exception:
        pass

    try:
        from mcp_tools.executors.zoom_rest import zoom_create_meeting
        result = await zoom_create_meeting(
            company_id=company_id,
            topic=topic,
            start_time=start_time.isoformat(),
            duration_minutes=duration_minutes,
            attendee_email=attendee_email or "",
        )
        if result.get("error"):
            logger.warning("[book_meeting] Zoom fallback failed for company %s: %s", company_id, result["error"])
            combined = f"{result.get('error') or ''} {result.get('next_suggestion') or ''}"
            if "meeting:write" in combined:
                hint = result.get("next_suggestion") or result["error"]
            else:
                hint = generic_failure_hint
            return None, None, hint
        # zoom_create_meeting returns ToolResult.ok(data).model_dump() — the join
        # URL lives under 'data'. Accept both shapes defensively.
        payload = result.get("data") if isinstance(result.get("data"), dict) else result
        return payload.get("join_url"), payload.get("meeting_id"), None
    except Exception as exc:
        logger.warning("[book_meeting] Zoom fallback unavailable for company %s: %s", company_id, exc)
        return None, None, generic_failure_hint


async def _create_teams_meeting_link(
    session: Session,
    company_id: int,
    subject: str,
    start_time: datetime,
    duration_minutes: int = 30,
    attendee_email: str | None = None,
    attendee_name: str | None = None,
    description: str = "",
) -> tuple[str | None, str | None, str | None]:
    """Create a Microsoft 365 calendar event with a Teams join link.

    This is an optional fallback. An unconnected Microsoft account is treated
    as a normal miss so booking can continue to Zoom.
    """
    try:
        from routes.microsoft_oauth import get_company_microsoft_token
        if not get_company_microsoft_token(session, company_id):
            return None, None, None

        from mcp_tools.executors.microsoft import ms_create_event
        result = await ms_create_event(
            company_id=company_id,
            subject=subject,
            start_time=start_time.isoformat(),
            end_time=(start_time + timedelta(minutes=duration_minutes)).isoformat(),
            invitee_email=attendee_email or "",
            invitee_name=attendee_name or "",
            notes=description,
            create_online_meeting=True,
        )
        if result.get("error"):
            logger.warning("[book_meeting] Microsoft Teams fallback failed for company %s: %s", company_id, result["error"])
            return None, None, "Microsoft Teams meeting could not be created."
        payload = result.get("data") if isinstance(result.get("data"), dict) else result
        join_url = payload.get("online_meeting_url")
        return join_url, payload.get("event_id") if join_url else None, None
    except Exception as exc:
        logger.warning("[book_meeting] Microsoft Teams fallback unavailable for company %s: %s", company_id, exc)
        return None, None, "Microsoft Teams meeting could not be created."


async def _schedule_via_connected_provider(
    *,
    session: Session,
    company_id: int,
    subject: str,
    description: str,
    start_time: datetime,
    duration_minutes: int,
    attendee_email: str | None,
    attendee_name: str | None,
    preferred_provider: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Schedule through the connected provider capability, independent of vendor."""
    from services.mcp.capability_router import route_capability

    if start_time.tzinfo is None:
        raise ValueError("Provider scheduling requires a timezone-aware start time")
    start_utc = start_time.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=duration_minutes)
    result = await route_capability(
        session=session,
        company_id=company_id,
        capability="schedule_meeting",
        user_id=0,
        arguments={
            "provider": preferred_provider,
            "subject": subject,
            "start_time": start_utc.isoformat(),
            "end_time": end_utc.isoformat(),
            "invitee_email": attendee_email or "",
            "invitee_name": attendee_name or "",
            "notes": description,
            "duration_minutes": duration_minutes,
        },
    )
    if result.get("error") or result.get("success") is False:
        raise RuntimeError(result.get("error") or "No connected scheduling provider could create the meeting")

    payload = result.get("data") if isinstance(result.get("data"), dict) else result
    meeting_link = (
        payload.get("meeting_link")
        or payload.get("meet_link")
        or payload.get("online_meeting_url")
        or payload.get("join_url")
        or payload.get("booking_url")
    )
    event_id = payload.get("calendar_event_id") or payload.get("event_id") or payload.get("booking_id")
    provider = payload.get("provider") or result.get("provider") or preferred_provider or "scheduling_provider"
    calendar_link = payload.get("calendar_link")
    return meeting_link, event_id, provider, calendar_link


async def book_meeting(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    proposed_time: str,
    meeting_type: str = "demo",
    lead_email: str | None = None,
) -> dict[str, Any]:
    lead = get_lead_or_404(session, company_id, lead_id)
    if lead_email:
        lead.email = lead_email.strip().lower()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        session.refresh(lead)

    # Dedup: return existing scheduled appointment if one already exists for this lead
    existing = _find_existing_appointment(session, company_id, lead.id, products=None)
    if existing:
        logger.info(
            "[book_meeting] Dedup — lead %d already has appointment %d at %s",
            lead.id, existing.id, existing.appointment_time,
        )
        return {
            "confirmed": True,
            "appointment_id": existing.id,
            "lead_id": lead.id,
            "lead_name": lead.name,
            "lead_email": lead.email,
            "appointment_time": existing.appointment_time.isoformat(),
            "email_sent": False,
            "message": f"{meeting_type.title()} already scheduled for {lead.name} — returning existing booking.",
            "duplicate": True,
        }

    appointment_time = await resolve_meeting_time_for_lead(session, company_id, lead, proposed_time)
    timezone_str = resolve_lead_timezone(lead, session=session, company_id=company_id)
    appointment_time_text = format_datetime_for_timezone(appointment_time, timezone_str)
    # Use structured notes format so the journey parser renders correctly
    # Try to create a Google Calendar event with Meet link
    meet_link: str | None = None
    calendar_event_id: str | None = None
    meet_link, calendar_event_id = _create_calendar_event_with_meet(
        session=session,
        company_id=company_id,
        summary=f"{meeting_type.title()} with {lead.name}",
        description=(
            f"Rio Sales Assistant – {meeting_type.title()} Meeting\n"
            f"Lead: {lead.name}\nEmail: {lead.email or ''}"
        ),
        start_time=appointment_time,
        duration_minutes=30,
        attendee_email=lead.email,
    )
    # Fallback order: Google Meet → Microsoft Teams → Zoom.
    meeting_provider: str | None = "google_meet" if meet_link else None
    meeting_link_hint: str | None = None
    if not meet_link:
        meet_link, calendar_event_id, meeting_link_hint = await _create_teams_meeting_link(
            session=session,
            company_id=company_id,
            subject=f"{meeting_type.title()} with {lead.name}",
            start_time=appointment_time,
            duration_minutes=30,
            attendee_email=lead.email,
            attendee_name=lead.name,
            description=f"Rio Sales Assistant – {meeting_type.title()} Meeting\nLead: {lead.name}\nEmail: {lead.email or ''}",
        )
        if meet_link:
            meeting_provider = "microsoft_teams"
    if not meet_link:
        meet_link, zoom_id, meeting_link_hint = await _create_zoom_meeting_link(
            session=session,
            company_id=company_id,
            topic=f"{meeting_type.title()} with {lead.name}",
            start_time=appointment_time,
            duration_minutes=30,
            attendee_email=lead.email,
        )
        if meet_link:
            meeting_provider = "zoom"

    appointment = Appointment(
        company_id=company_id,
        lead_id=lead.id,
        owner_user_id=lead.owner_user_id or actor_user_id,
        appointment_time=appointment_time,
        status="scheduled",
        notes=f"demo type={meeting_type}; location=online; meeting_provider={meeting_provider or 'none'}",
        meeting_link=meet_link,
        calendar_event_id=calendar_event_id,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)

    try:
        from services.call.outcome_service import advance_ism_stage
        if advance_ism_stage(lead, "engaged"):
            lead.updated_at = utc_now()
            lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
    except Exception:
        pass

    email_sent = False
    provider_label = meeting_provider_display(meeting_provider, meet_link)
    if lead.email:
        try:
            meet_line = f"\n\nJoin the {provider_label} meeting: {meet_link}" if meet_link else ""
            send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                subject=f"{meeting_type.title()} scheduled",
                body=f"Your {meeting_type} is scheduled for {appointment_time_text}.{meet_line}",
            )
            email_sent = True
        except Exception:
            email_sent = False

    message = f"{meeting_type.title()} scheduled for {lead.name}."
    if meet_link:
        message += f" {provider_label}: {meet_link}"
    if meeting_link_hint:
        # Surfaces in the agent's booking summary why no join link exists (e.g.
        # the meeting:write scope hint) so the rep/admin knows the next step.
        message += f" Note: {meeting_link_hint}"

    return {
        "confirmed": True,
        "appointment_id": appointment.id,
        "lead_id": lead.id,
        "lead_name": lead.name,
        "lead_email": lead.email,
        "appointment_time": appointment_time.isoformat(),
        "meeting_link": meet_link,
        "meeting_provider": meeting_provider,
        "meeting_link_hint": meeting_link_hint,
        "email_sent": email_sent,
        "message": message,
    }


async def book_demo(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    name: str,
    phone: str,
    demo_date: str,
    products: str,
    demo_type: str = "Offline",
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    email: str | None = None,
    notes: str | None = None,
    duration_minutes: int = 30,
    provider: str | None = None,
) -> dict[str, Any]:
    lead_info = get_or_create_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        name=name,
        phone=phone,
        email=email,
    )
    actual_lead_id = int(lead_info["lead_id"]) if lead_info.get("lead_id") else lead_id
    lead = get_lead_or_404(session, company_id, actual_lead_id)
    lead_updated = False
    if city and not lead.city:
        lead.city = city
        lead_updated = True
    if state and not lead.state:
        lead.state = state
        lead_updated = True
    if pincode and not lead.pincode:
        lead.pincode = pincode
        lead_updated = True
    if email and not lead.email:
        lead.email = email.strip().lower()
        lead_updated = True
    if lead_updated or not lead.timezone:
        lead.timezone = resolve_lead_timezone(lead, session=session, company_id=company_id)
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        session.refresh(lead)

    if not lead.email:
        return {
            "success": False,
            "lead_id": lead.id,
            "error": "A confirmation email address is required before scheduling this demo.",
            "next_suggestion": "Collect and verify the lead's email address, then retry schedule_demo.",
        }

    # Dedup: if a scheduled appointment with overlapping products already exists, return it
    existing = _find_existing_appointment(session, company_id, lead.id, products=products)
    if existing:
        logger.info(
            "[book_demo] Dedup — lead %d already has appointment %d for similar products at %s",
            lead.id, existing.id, existing.appointment_time,
        )
        m = re.search(r"products=([^;]+)", existing.notes or "", re.IGNORECASE)
        existing_products = m.group(1).strip() if m else products
        return {
            "success": True,
            "lead_id": lead.id,
            "appointment_id": existing.id,
            "demo_type": demo_type,
            "products": existing_products,
            "requested_time": None,
            "appointment_time": existing.appointment_time.isoformat(),
            "timezone": resolve_lead_timezone(lead, session=session, company_id=company_id),
            "meeting_link": existing.meeting_link,
            "calendar_event_id": existing.calendar_event_id,
            "email_sent": False,
            "message": f"Demo already scheduled for {lead.name} — returning existing booking.",
            "duplicate": True,
        }

    appointment_time = await resolve_meeting_time_for_lead(session, company_id, lead, demo_date)
    timezone_str = resolve_lead_timezone(lead, session=session, company_id=company_id)
    appointment_time_text = format_datetime_for_timezone(appointment_time, timezone_str)
    location_parts = [part for part in [city, state, pincode] if part]
    location_text = ", ".join(location_parts) if location_parts else "online"

    # Persist the canonical appointment before contacting an external provider.
    # The provider is a later side effect; the database record remains the
    # source of truth even if the provider is temporarily unavailable.
    meet_link: str | None = None
    calendar_event_id: str | None = None
    meeting_provider: str | None = None
    meeting_link_hint: str | None = None
    appointment = Appointment(
        company_id=company_id,
        lead_id=lead.id,
        owner_user_id=lead.owner_user_id or actor_user_id,
        appointment_time=appointment_time,
        status="scheduled",
        notes=(
            f"Demo type={demo_type}; products={products}; location={location_text}; "
            f"notes={notes or ''}; meeting_provider=none"
        ).strip(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)

    provider_error: str | None = None
    if str(demo_type or "").strip().lower() == "online":
        try:
            meet_link, calendar_event_id, meeting_provider, _calendar_link = await _schedule_via_connected_provider(
                session=session,
                company_id=company_id,
                subject=f"Online Demo: {products or 'Products'} with {lead.name}",
                description=(
                    f"Online demo scheduled by Rio Sales Assistant.\n"
                    f"Lead: {lead.name}\nProducts: {products}"
                ),
                start_time=appointment_time,
                duration_minutes=duration_minutes,
                attendee_email=lead.email,
                attendee_name=lead.name,
                preferred_provider=provider,
            )
        except Exception as exc:
            meeting_link_hint = str(exc)
            provider_error = meeting_link_hint

    appointment.meeting_link = meet_link
    appointment.calendar_event_id = calendar_event_id
    appointment.notes = (
        f"Demo type={demo_type}; products={products}; location={location_text}; "
        f"notes={notes or ''}; meeting_provider={meeting_provider or 'none'}"
    ).strip()
    appointment.updated_by = actor_user_id
    appointment.updated_at = utc_now()
    session.add(appointment)
    session.commit()
    session.refresh(appointment)

    if provider_error:
        return {
            "success": False,
            "lead_id": lead.id,
            "appointment_id": appointment.id,
            "requested_time": demo_date,
            "appointment_time": appointment_time.isoformat(),
            "timezone": timezone_str,
            "provider": None,
            "meeting_link": None,
            "email_sent": False,
            "error": f"Appointment saved, but no connected meeting provider could create the meeting: {provider_error}",
            "next_suggestion": "Connect a scheduling provider or retry the booking; do not send a manual confirmation.",
        }

    # Advance ISM stage to "engaged" — they agreed to a demo
    try:
        from services.call.outcome_service import advance_ism_stage
        if advance_ism_stage(lead, "engaged"):
            lead.updated_at = utc_now()
            lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
    except Exception:
        pass

    interaction = Interaction(
        company_id=company_id,
        lead_id=lead.id,
        user_id=actor_user_id,
        type="demo",
        channel="call",
        direction="outbound",
        source="voice_agent",
        content=f"Demo booked for {products}",
        metadata_json={
            "demo_type": demo_type,
            "products": products,
            "requested_demo_date": demo_date,
            "resolved_appointment_time": appointment_time.isoformat(),
            "lead_timezone": timezone_str,
            "city": city,
            "state": state,
            "pincode": pincode,
            "notes": notes,
        },
        status="completed",
        started_at=utc_now(),
        ended_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(interaction)
    session.commit()

    email_sent = False
    provider_label = meeting_provider_display(meeting_provider, meet_link)
    if lead.email:
        try:
            meet_line = f"\n\nJoin the {provider_label} demo here: {meet_link}" if meet_link else ""
            send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                subject=f"{demo_type} demo scheduled",
                body=(
                    f"Your {demo_type.lower()} demo for {products} is scheduled for "
                    f"{appointment_time_text}.{meet_line}"
                ),
            )
            email_sent = True
        except Exception:
            email_sent = False

    if lead.email and not email_sent:
        return {
            "success": False,
            "lead_id": lead.id,
            "appointment_id": appointment.id,
            "requested_time": demo_date,
            "appointment_time": appointment_time.isoformat(),
            "timezone": timezone_str,
            "meeting_link": meet_link,
            "calendar_event_id": calendar_event_id,
            "meeting_provider": meeting_provider,
            "email_sent": False,
            "error": "Appointment and provider meeting were created, but confirmation email failed.",
            "next_suggestion": "Retry confirmation delivery using the saved appointment; do not create another appointment.",
        }

    message = f"{demo_type} demo scheduled for {lead.name}."
    if meet_link:
        message += f" {provider_label}: {meet_link}"
    if meeting_link_hint:
        # Surfaces in the agent's booking summary why no join link exists (e.g.
        # the meeting:write scope hint) so the rep/admin knows the next step.
        message += f" Note: {meeting_link_hint}"

    return {
        "success": True,
        "lead_id": lead.id,
        "appointment_id": appointment.id,
        "demo_type": demo_type,
        "products": products,
        "requested_time": demo_date,
        "appointment_time": appointment_time.isoformat(),
        "timezone": timezone_str,
        "meeting_link": meet_link,
        "calendar_event_id": calendar_event_id,
        "meeting_provider": meeting_provider,
        "meeting_link_hint": meeting_link_hint,
        "email_sent": email_sent,
        "message": message,
    }


def send_communication(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    channels: list[str],
    content: str,
    subject: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    lead = get_lead_or_404(session, company_id, lead_id)
    normalized_channels: list[str] = []
    for channel in channels or []:
        channel_name = str(channel or "").strip().lower()
        if channel_name in {"email", "whatsapp"} and channel_name not in normalized_channels:
            normalized_channels.append(channel_name)

    if email:
        lead.email = email.strip().lower()
    if phone:
        lead.normalized_phone = normalize_phone(phone)
    if email or phone:
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        session.refresh(lead)

    if "email" in normalized_channels and _has_recent_demo_confirmation(
        session,
        company_id=company_id,
        lead_id=lead_id,
        content=content,
    ):
        return {
            "success": True,
            "deduplicated": True,
            "message": "Duplicate demo confirmation suppressed; the booking email was already sent.",
            "channel_status": {"email": "deduplicated"},
            "results": [],
        }

    results: list[dict[str, Any]] = []
    missing_info: list[dict[str, str]] = []

    if "email" in normalized_channels:
        if not lead.email:
            missing_info.append({
                "channel": "email",
                "missing": "email_address",
                "ask": "Ask the lead for their email address, then call send_communication again with the email parameter.",
            })
            results.append({"channel": "email", "success": False, "error": "no_email"})
        else:
            try:
                results.append(
                    send_email_to_lead(
                        session=session,
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        lead_id=lead.id,
                        subject=subject or "Message from Rio",
                        body=content,
                    )
                )
            except Exception as exc:
                results.append({"channel": "email", "success": False, "error": str(exc)})

    if "whatsapp" in normalized_channels:
        if not lead.normalized_phone:
            missing_info.append({
                "channel": "whatsapp",
                "missing": "phone_number",
                "ask": "Ask the lead for their WhatsApp number, then call send_communication again with the phone parameter.",
            })
            results.append({"channel": "whatsapp", "success": False, "error": "no_phone"})
        else:
            try:
                results.append(
                    send_whatsapp_to_lead(
                        session=session,
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        lead_id=lead.id,
                        body=content,
                    )
                )
            except Exception as exc:
                results.append({"channel": "whatsapp", "success": False, "error": str(exc)})

    completed_channels = [
        item.get("channel")
        for item in results
        if item.get("success") and not item.get("queued")
    ]
    queued_channels = [
        item.get("channel")
        for item in results
        if item.get("success") and item.get("queued")
    ]
    failed_channels = [
        item.get("channel")
        for item in results
        if not item.get("success")
    ]

    channel_status: dict[str, str] = {}
    for item in results:
        channel_name = item.get("channel")
        if not channel_name:
            continue
        if item.get("success") and item.get("queued"):
            channel_status[channel_name] = "queued"
        elif item.get("success"):
            channel_status[channel_name] = "sent"
        else:
            channel_status[channel_name] = "failed"

    # Build a human-readable status message
    parts: list[str] = []
    if completed_channels:
        parts.append(f"Sent via {', '.join(completed_channels)}.")
    if queued_channels:
        parts.append(f"Queued via {', '.join(queued_channels)}.")
    if missing_info:
        for m in missing_info:
            parts.append(f"Could not send via {m['channel']}: {m['missing']} not on file. {m['ask']}")
    elif failed_channels:
        parts.append(f"Failed via {', '.join(failed_channels)}.")

    return {
        "success": any(item.get("success") for item in results),
        "lead_id": lead.id,
        "requested_channels": normalized_channels,
        "completed_channels": completed_channels,
        "queued_channels": queued_channels,
        "failed_channels": failed_channels,
        "channel_status": channel_status,
        "missing_info": missing_info,
        "results": results,
        "message": " ".join(parts) if parts else "No valid communication channels were requested.",
    }


def sync_product_catalog(
    session: Session,
    company_id: int,
) -> dict[str, Any]:
    products = session.exec(
        select(Product).where(Product.company_id == company_id)
    ).all()
    if not sync_products_to_chroma:
        return {
            "status": "unavailable",
            "message": "Product sync backend is not available in this runtime.",
        }
    sync_products_to_chroma(products)
    return {
        "status": "success",
        "synced_count": len(products),
    }


def get_call_latency_summary(interaction_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        logs = session.exec(
            select(LatencyLog).where(LatencyLog.interaction_id == interaction_id)
        ).all()

    if not logs:
        return {
            "status": "not_found",
            "interaction_id": interaction_id,
            "message": "No latency data found for this interaction.",
        }

    total_stt = sum(float(item.stt_ms) for item in logs)
    total_llm = sum(float(item.llm_ms) for item in logs)
    total_tts = sum(float(item.tts_ms) for item in logs)
    total_all = sum(float(item.total_ms) for item in logs)
    count = len(logs)

    return {
        "status": "ok",
        "interaction_id": interaction_id,
        "turns": count,
        "avg_stt_ms": round(total_stt / count, 2),
        "avg_llm_ms": round(total_llm / count, 2),
        "avg_tts_ms": round(total_tts / count, 2),
        "avg_total_ms": round(total_all / count, 2),
        "stt_providers": sorted({item.stt_provider for item in logs if item.stt_provider}),
        "llm_models": sorted({item.llm_model for item in logs if item.llm_model}),
        "tts_providers": sorted({item.tts_provider for item in logs if item.tts_provider}),
    }


def get_google_auth_url(session: Session, company_id: int, actor_user_id: int) -> dict[str, Any]:
    return {
        "success": False,
        "message": (
            "Google Calendar auth is not available from the current tenant-safe tool path yet. "
            "Migrate google_calendar_service.py to the current User schema first."
        ),
        "company_id": company_id,
        "user_id": actor_user_id,
    }


def submit_google_auth_code(
    session: Session,
    company_id: int,
    actor_user_id: int,
    code: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "message": (
            "Google Calendar auth code submission is not available from the current tenant-safe "
            "tool path yet."
        ),
        "company_id": company_id,
        "user_id": actor_user_id,
        "code_received": bool(code),
    }
