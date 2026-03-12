import logging
from datetime import datetime, timezone
from sqlmodel import Session, select
from models.models import Lead, Interaction, Appointment, Demo

logger = logging.getLogger(__name__)

def get_comprehensive_lead_context(session: Session, lead_id: int) -> str:
    """
    Fetches lead data + history (last 3 interactions, scheduled appointments, demo requests)
    and returns a formatted string for LLM system prompt injection.
    """
    if not lead_id or lead_id <= 0:
        return None

    try:
        lead = session.get(Lead, lead_id)
        if not lead:
            return None

        # 1. Basic Lead Info
        parts = [f"Name: {lead.name}", f"Phone: {lead.phone}"]
        id_part = f"[__META_ID__]: {lead.id}"
        if lead.email: parts.append(f"Email: {lead.email}")
        if lead.status: parts.append(f"Status: {lead.status}")
        if lead.notes: parts.append(f"Lead Notes: {lead.notes}")
        lead_data_str = ", ".join(parts)
        
        # 2. Past Interactions (Last 3)
        interactions = session.exec(
            select(Interaction)
            .where(Interaction.lead_id == lead_id)
            .order_by(Interaction.timestamp.desc())
            .limit(3)
        ).all()
        interaction_history = "\n".join([f"- {i.timestamp.strftime('%Y-%m-%d')}: {i.type} - {i.content}" for i in interactions])
        
        # 3. Scheduled Appointments (Handle case sensitivity in status)
        appointments = session.exec(
            select(Appointment)
            .where(Appointment.lead_id == lead_id)
            .where(Appointment.status.in_(["Scheduled", "scheduled"]))
        ).all()
        appointment_list = "\n".join([f"- {a.appointment_time.strftime('%Y-%m-%d %H:%M') if a.appointment_time else 'N/A'}: {a.status} - {a.notes or 'No notes'}" for a in appointments])
        
        # 4. Demo History
        demos = session.exec(
            select(Demo)
            .where(Demo.lead_id == lead_id)
        ).all()
        demo_list = "\n".join([f"- {d.demo_date.strftime('%Y-%m-%d') if d.demo_date else 'N/A'}: {d.status} ({d.demo_type}) - Products: {d.products or 'N/A'}. Notes: {d.notes or 'No notes'}" for d in demos])

        # Build final context
        context = f"[PROSPECT DATA]\n{lead_data_str}\n{id_part}\n\n"
        if interaction_history: 
            context += f"[PAST INTERACTIONS]\n{interaction_history}\n\n"
        if appointment_list: 
            context += f"[SCHEDULED APPOINTMENTS]\n{appointment_list}\n\n"
        if demo_list: 
            context += f"[DEMO HISTORY]\n{demo_list}\n"
            
        return context
    except Exception as e:
        logger.error(f"❌ Error fetching comprehensive lead context for #{lead_id}: {e}", exc_info=True)
        return None
