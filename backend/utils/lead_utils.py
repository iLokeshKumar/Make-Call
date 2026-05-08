import logging

from sqlmodel import Session, select

from models.models import Appointment, Interaction, Lead
from utils.timezone_utils import format_datetime_for_timezone, resolve_lead_timezone

logger = logging.getLogger(__name__)


def get_comprehensive_lead_context(session: Session, lead_id: int) -> str | None:
    if not lead_id or lead_id <= 0:
        return None

    try:
        lead = session.get(Lead, lead_id)
        if not lead:
            return None

        parts = [f"Name: {lead.name}", f"Phone: {lead.normalized_phone}"]
        if lead.email:
            parts.append(f"Email: {lead.email}")
        timezone_str = resolve_lead_timezone(lead, session=session, company_id=lead.company_id)
        if timezone_str:
            parts.append(f"Timezone: {timezone_str}")
        if lead.preferred_language:
            parts.append(f"Preferred Language: {lead.preferred_language}")
        if lead.city:
            parts.append(f"City: {lead.city}")
        if lead.state:
            parts.append(f"State: {lead.state}")
        if lead.country:
            parts.append(f"Country: {lead.country}")
        if lead.pincode:
            parts.append(f"Pincode: {lead.pincode}")
        if lead.job_title:
            parts.append(f"Title: {lead.job_title}")
        if lead.industry:
            parts.append(f"Industry: {lead.industry}")
        if lead.status:
            parts.append(f"Status: {lead.status}")
        if lead.notes:
            parts.append(f"Lead Notes: {lead.notes}")

        interactions = session.exec(
            select(Interaction)
            .where(Interaction.lead_id == lead_id)
            .order_by(Interaction.started_at.desc())
            .limit(3)
        ).all()
        interaction_history = "\n".join(
            f"- {item.started_at.strftime('%Y-%m-%d')}: {item.type} - {item.content or ''}"
            for item in interactions
        )

        appointments = session.exec(
            select(Appointment)
            .where(Appointment.lead_id == lead_id)
            .where(Appointment.status.in_(["scheduled", "Scheduled"]))
        ).all()
        appointment_list = "\n".join(
            f"- {format_datetime_for_timezone(item.appointment_time, timezone_str)}: {item.status} - {item.notes or 'No notes'}"
            for item in appointments
        )

        context = f"[PROSPECT DATA]\n{', '.join(parts)}\n[__META_ID__]: {lead.id}\n\n"
        if interaction_history:
            context += f"[PAST INTERACTIONS]\n{interaction_history}\n\n"
        if appointment_list:
            context += f"[SCHEDULED APPOINTMENTS]\n{appointment_list}\n"

        return context
    except Exception as exc:
        logger.error("Error fetching lead context for %s: %s", lead_id, exc, exc_info=True)
        return None
