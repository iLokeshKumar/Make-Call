from __future__ import annotations

import logging
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
    parsed = _parse_iso_datetime(raw_value)
    if parsed:
        return parsed
    if normalize_date_ai:
        normalized = await normalize_date_ai(raw_value)
        if normalized:
            if normalized.tzinfo is None:
                return normalized.replace(tzinfo=timezone.utc)
            return normalized
    return utc_now() + timedelta(days=1)


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

    lead = Lead(
        company_id=company_id,
        owner_user_id=actor_user_id,
        name=name.strip(),
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

    appointment_time = await resolve_meeting_time(proposed_time)
    # Use structured notes format so the journey parser renders correctly
    appointment = Appointment(
        company_id=company_id,
        lead_id=lead.id,
        owner_user_id=lead.owner_user_id or actor_user_id,
        appointment_time=appointment_time,
        status="scheduled",
        notes=f"demo type={meeting_type}; location=online",
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
    if lead.email:
        try:
            send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                subject=f"{meeting_type.title()} scheduled",
                body=f"Your {meeting_type} is scheduled for {appointment_time.isoformat()}.",
            )
            email_sent = True
        except Exception:
            email_sent = False

    return {
        "confirmed": True,
        "appointment_id": appointment.id,
        "lead_id": lead.id,
        "lead_name": lead.name,
        "lead_email": lead.email,
        "appointment_time": appointment_time.isoformat(),
        "email_sent": email_sent,
        "message": f"{meeting_type.title()} scheduled for {lead.name}.",
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
            "appointment_time": existing.appointment_time.isoformat(),
            "email_sent": False,
            "message": f"Demo already scheduled for {lead.name} — returning existing booking.",
            "duplicate": True,
        }

    appointment_time = await resolve_meeting_time(demo_date)
    location_parts = [part for part in [city, state, pincode] if part]
    location_text = ", ".join(location_parts) if location_parts else "online"
    appointment = Appointment(
        company_id=company_id,
        lead_id=lead.id,
        owner_user_id=lead.owner_user_id or actor_user_id,
        appointment_time=appointment_time,
        status="scheduled",
        notes=f"Demo type={demo_type}; products={products}; location={location_text}; notes={notes or ''}".strip(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)

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
    if lead.email:
        try:
            send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                subject=f"{demo_type} demo scheduled",
                body=(
                    f"Your {demo_type.lower()} demo for {products} is scheduled for "
                    f"{appointment_time.isoformat()}."
                ),
            )
            email_sent = True
        except Exception:
            email_sent = False

    return {
        "success": True,
        "lead_id": lead.id,
        "appointment_id": appointment.id,
        "demo_type": demo_type,
        "products": products,
        "appointment_time": appointment_time.isoformat(),
        "email_sent": email_sent,
        "message": f"{demo_type} demo scheduled for {lead.name}.",
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

    results: list[dict[str, Any]] = []
    if "email" in channels:
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
    if "whatsapp" in channels:
        results.append(
            send_whatsapp_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                body=content,
            )
        )

    return {
        "success": any(item.get("success") for item in results),
        "lead_id": lead.id,
        "results": results,
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
