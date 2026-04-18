from __future__ import annotations

import time
import logging
from decimal import Decimal
from typing import Any

import requests
from sqlmodel import Session, func, select

from credentials_service import get_company_setting_value
from models.models import CallTask, EngagementEvent, Interaction, Lead, utc_now
from services.call.outbound_call_service import create_call_task

logger = logging.getLogger(__name__)

# Apollo People Match endpoint — enriches a lead using email/name
_APOLLO_PEOPLE_MATCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"


def _score_to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 2))).quantize(Decimal("0.01"))


def _fetch_interaction_counts(session: Session, company_id: int, lead_id: int) -> dict[str, int]:
    """Return per-channel outbound interaction counts for a lead."""
    rows = session.exec(
        select(Interaction.channel, func.count(Interaction.id)).where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead_id,
            Interaction.direction == "outbound",
        ).group_by(Interaction.channel)
    ).all()
    return {(channel or "unknown"): count for channel, count in rows}


def _fetch_engagement_counts(session: Session, company_id: int, lead_id: int) -> dict[str, int]:
    """Return engagement event type counts for a lead (opens, clicks, replies, etc.)."""
    rows = session.exec(
        select(EngagementEvent.event_type, func.count(EngagementEvent.id)).where(
            EngagementEvent.company_id == company_id,
            EngagementEvent.lead_id == lead_id,
        ).group_by(EngagementEvent.event_type)
    ).all()
    return {event_type: count for event_type, count in rows}


def compute_icp_score(
    lead: Lead,
    interaction_counts: dict[str, int] | None = None,
    engagement_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Score a lead 0–100 based on profile completeness, interaction history,
    and engagement signals.

    Profile completeness (max 60 pts):
      email=20, website=15, target_industry=25 (capped at 60 together
      with seniority/source/enrichment adjustments)
    Interaction history (max 20 pts):
      call≥1: +8, whatsapp≥1: +6, email≥1: +6
    Engagement signals (max 20 pts):
      reply≥1: +10, click≥1: +6, open≥2: +4
    """
    score = 0.0
    reasons: list[str] = []

    # Profile completeness
    if lead.email:
        score += 20
        reasons.append("lead_has_email")
    if lead.website:
        score += 15
        reasons.append("lead_has_website")
    if lead.industry and lead.industry.lower() in {
        "tech", "saas", "manufacturing", "electronics",
        "healthcare", "finance", "retail", "distribution",
    }:
        score += 25
        reasons.append("target_industry_match")
    if lead.job_title and any(
        kw in lead.job_title.lower()
        for kw in ["manager", "head", "director", "owner", "founder", "vp", "cxo", "ceo", "cto", "coo"]
    ):
        score += 15
        reasons.append("decision_maker_seniority")
    if lead.source and lead.source.lower() in {"apollo api", "apollo", "voice_agent"}:
        score += 10
        reasons.append("high_intent_source")
    if lead.enrichment_status and lead.enrichment_status.lower() != "not_enriched":
        score += 15
        reasons.append("already_enriched")

    # Interaction history (shows we've reached them before)
    ic = interaction_counts or {}
    if ic.get("call", 0) >= 1:
        score += 8
        reasons.append("prior_call_contact")
    if ic.get("whatsapp", 0) >= 1:
        score += 6
        reasons.append("prior_whatsapp_contact")
    if ic.get("email", 0) >= 1:
        score += 6
        reasons.append("prior_email_contact")

    # Engagement signals (they responded/interacted)
    ec = engagement_counts or {}
    if ec.get("reply", 0) >= 1 or ec.get("whatsapp_reply", 0) >= 1:
        score += 10
        reasons.append("lead_replied")
    if ec.get("email_click", 0) >= 1 or ec.get("click", 0) >= 1:
        score += 6
        reasons.append("link_clicked")
    if ec.get("email_open", 0) >= 2 or ec.get("open", 0) >= 2:
        score += 4
        reasons.append("email_opened_multiple_times")

    priority = "low"
    if score >= 70:
        priority = "high"
    elif score >= 40:
        priority = "medium"

    return {
        "score": _score_to_decimal(min(score, 100)),
        "reasons": reasons,
        "priority": priority,
    }


def score_lead(session: Session, company_id: int, lead_id: int) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    interaction_counts = _fetch_interaction_counts(session, company_id, lead_id)
    engagement_counts = _fetch_engagement_counts(session, company_id, lead_id)
    scoring = compute_icp_score(lead, interaction_counts, engagement_counts)
    lead.lead_score = scoring["score"]
    lead.lead_score_reasons_json = {"reasons": scoring["reasons"], "priority": scoring["priority"]}
    lead.updated_at = utc_now()
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {
        "lead_id": lead.id,
        "score": str(lead.lead_score) if lead.lead_score is not None else None,
        "priority": scoring["priority"],
        "reasons": scoring["reasons"],
    }


def _enrichment_quality_check(lead: Lead) -> dict[str, Any]:
    """Assess whether enrichment produced useful data."""
    populated = []
    missing = []
    for field, value in [
        ("email", lead.email),
        ("industry", lead.industry),
        ("job_title", lead.job_title),
        ("website", lead.website),
        ("country", lead.country),
    ]:
        (populated if value else missing).append(field)
    quality = "high" if len(populated) >= 4 else "medium" if len(populated) >= 2 else "low"
    return {"quality": quality, "populated_fields": populated, "missing_fields": missing}


def _apollo_people_match(lead: Lead, api_key: str) -> bool:
    """
    Call Apollo People Match API to enrich a lead.
    Fills: job_title, company_name, industry, city, state, country, website.
    Returns True if at least one field was populated.
    """
    if not api_key:
        return False

    payload: dict[str, Any] = {"reveal_personal_emails": False}
    if lead.email:
        payload["email"] = lead.email
    if lead.name:
        parts = lead.name.strip().split(maxsplit=1)
        payload["first_name"] = parts[0]
        if len(parts) > 1:
            payload["last_name"] = parts[1]
    if lead.company_name:
        payload["organization_name"] = lead.company_name

    if not payload.get("email") and not (payload.get("first_name") and payload.get("last_name")):
        return False  # Apollo requires email OR full name

    try:
        resp = requests.post(
            _APOLLO_PEOPLE_MATCH_URL,
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.info("[Apollo] No match found for lead %s", lead.id)
            return False
        raise

    person = data.get("person") or {}
    if not person:
        return False

    org = person.get("organization") or {}
    updated = False

    def _set(attr: str, value: Any) -> None:
        nonlocal updated
        if value and not getattr(lead, attr, None):
            setattr(lead, attr, value)
            updated = True

    _set("email",        person.get("email"))
    _set("job_title",    person.get("title"))
    _set("company_name", org.get("name") or person.get("organization_name"))
    _set("industry",     org.get("industry"))
    _set("city",         person.get("city"))
    _set("state",        person.get("state"))
    _set("country",      person.get("country"))
    _set("website",      org.get("website_url"))

    if updated:
        logger.info(
            "[Apollo] Enriched lead %s (%s) via People Match",
            lead.id, lead.name,
        )
    return updated


def _attempt_enrich(lead: Lead, actor_user_id: int, apollo_api_key: str | None = None) -> bool:
    """
    Waterfall enrichment for a single lead.

    Step 1 — Apollo People Match (if API key is available):
        Fills job_title, company_name, industry, city, state, country, website.
    Step 2 — Domain inference (always runs as cheap fallback):
        Derives website from email domain when Apollo didn't fill it.

    Returns True if any field was updated.
    """
    updated = False

    # Apollo People Match
    if apollo_api_key:
        try:
            if _apollo_people_match(lead, apollo_api_key):
                updated = True
        except Exception as exc:
            logger.warning("[Apollo] People Match failed for lead %s: %s", lead.id, exc)

    # Domain inference fallback — free, no API needed
    if lead.email and "@" in lead.email and not lead.website:
        domain = lead.email.split("@")[-1].strip().lower()
        if domain and "." in domain and domain not in {
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
            "icloud.com", "protonmail.com", "ymail.com",
        }:
            lead.website = f"https://{domain}"
            updated = True

    if updated and lead.enrichment_status == "not_enriched":
        lead.enrichment_status = "basic_enriched"

    return updated


def enrich_lead_if_needed(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    # Skip if already well-enriched.
    if lead.enrichment_status == "fully_enriched":
        quality = _enrichment_quality_check(lead)
        return {
            "lead_id": lead.id,
            "enrichment_status": lead.enrichment_status,
            "website": lead.website,
            "updated": False,
            "skipped": True,
            "skip_reason": "already_fully_enriched",
            "quality": quality,
        }

    # Resolve Apollo API key once per enrichment run (company-scoped credential)
    try:
        from credentials_service import get_company_credential
        apollo_key: str | None = get_company_credential(session, company_id, "APOLLO_API_KEY")
    except Exception:
        apollo_key = None

    updated = False
    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            updated = _attempt_enrich(lead, actor_user_id, apollo_api_key=apollo_key)
            last_error = None
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Enrichment attempt %d/%d failed for lead=%d: %s", attempt, max_attempts, lead_id, exc)
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))  # exponential backoff: 1s, 2s

    quality = _enrichment_quality_check(lead)

    if updated:
        lead.last_enriched_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        # Upgrade status based on quality.
        if quality["quality"] == "high":
            lead.enrichment_status = "fully_enriched"
        elif quality["quality"] == "medium":
            lead.enrichment_status = "basic_enriched"
        session.add(lead)
        session.commit()
        session.refresh(lead)

    return {
        "lead_id": lead.id,
        "enrichment_status": lead.enrichment_status,
        "website": lead.website,
        "updated": updated,
        "quality": quality,
        **({"error": last_error} if last_error else {}),
    }


def choose_outreach_strategy(session: Session, company_id: int, lead_id: int, score_payload: dict[str, Any]) -> dict[str, Any]:
    score_text = score_payload.get("score")
    score = Decimal(score_text) if score_text is not None else Decimal("0")
    if score >= Decimal("70"):
        return {
            "strategy": "immediate_call_task",
            "schedule_call": True,
            "delay_minutes": 5,
        }
    if score >= Decimal("40"):
        return {
            "strategy": "near_term_call_task",
            "schedule_call": True,
            "delay_minutes": 60,
        }
    return {
        "strategy": "nurture_only",
        "schedule_call": False,
        "delay_minutes": None,
    }


def _auto_trigger_enabled(session: Session, company_id: int) -> bool:
    value = get_company_setting_value(session, company_id, "AUTO_TRIGGER_NEW_LEADS")
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def trigger_new_lead_outreach(session: Session, company_id: int, actor_user_id: int, lead_id: int) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    enrichment_result = enrich_lead_if_needed(session, company_id, actor_user_id, lead_id)
    scoring = score_lead(session, company_id, lead_id)
    if scoring.get("error"):
        return scoring

    strategy = choose_outreach_strategy(session, company_id, lead_id, scoring)
    result: dict[str, Any] = {
        "lead_id": lead_id,
        "enrichment": enrichment_result,
        "scoring": scoring,
        "strategy": strategy,
    }

    if not _auto_trigger_enabled(session, company_id):
        result["auto_triggered"] = False
        result["reason"] = "AUTO_TRIGGER_NEW_LEADS disabled"
        return result

    if strategy["schedule_call"]:
        from datetime import timedelta

        scheduled_at = utc_now() + timedelta(minutes=int(strategy["delay_minutes"]))
        task = create_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            assigned_user_id=lead.owner_user_id or actor_user_id,
            scheduled_at=scheduled_at,
            notes=f"Auto-created from demand generation service ({strategy['strategy']})",
            dialer_source="demand_generation",
        )
        lead.next_action = "follow_up_call"
        lead.next_action_due_at = scheduled_at
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        result["auto_triggered"] = True
        result["call_task_id"] = task.id
        return result

    result["auto_triggered"] = False
    result["reason"] = "Lead scored below auto-call threshold"
    return result


def process_recent_unscored_leads(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.lead_score.is_(None),
        ).order_by(Lead.created_at.desc()).limit(limit)
    ).all()
    results: list[dict[str, Any]] = []
    for lead in leads:
        results.append(trigger_new_lead_outreach(session, company_id, actor_user_id, lead.id))
    return results


def get_scheduled_call_task_for_lead(session: Session, company_id: int, lead_id: int) -> CallTask | None:
    return session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.lead_id == lead_id,
            CallTask.dialer_source == "demand_generation",
        ).order_by(CallTask.created_at.desc())
    ).first()
