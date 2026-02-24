import os
from datetime import datetime
from sqlmodel import Session, select, text
from database import engine
from models.models import Appointment, Lead

from langchain_core.tools import tool

from google_calendar_service import create_google_meet_for_booking

@tool
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo", notes: str = "") -> dict:
    """
    Book a meeting/demo for a qualified lead (DETERMINISTIC TOOL).
    
    Args:
        lead_id: ID of the lead from database
        proposed_time: ISO format datetime (e.g., "2026-02-20T14:11:22")
        meeting_type: "demo", "consultation", "follow-up"
        notes: Additional notes for the meeting
    
    Returns:
        {
            "confirmed": bool,
            "appointment_id": int,
            "calendar_url": str,
            "google_meet_link": str,
            "lead_name": str,
            "lead_email": str,
            "message": str
        }
    """
    with Session(engine) as session:
        # Fetch lead info
        lead = session.get(Lead, lead_id)
        
        if not lead:
            return {
                "confirmed": False,
                "error": f"Lead with ID {lead_id} not found"
            }
        
        # Create appointment record
        try:
            appointment = Appointment(
                lead_id=lead_id,
                appointment_time=proposed_time,
                status="scheduled",
                type=meeting_type,
                notes=notes or f"Appointment for {meeting_type}"
            )
            
            # --- GOOGLE MEET INTEGRATION ---
            meet_result = create_google_meet_for_booking(
                lead_name=lead.name,
                lead_email=lead.email or "no-email@example.com",
                proposed_time=proposed_time,
                meeting_type=meeting_type
            )
            
            if meet_result.get("success"):
                appointment.meeting_link = meet_result.get("google_meet_link")
                appointment.calendar_event_id = meet_result.get("calendar_event_id")
                # Use real calendar link if available
                calendar_url = meet_result.get("calendar_link") or f"https://rio-crm.example.com/appointment/{appointment.id}"
            else:
                calendar_url = f"https://rio-crm.example.com/appointment/{appointment.id}"
            
            session.add(appointment)
            session.commit()
            session.refresh(appointment)
            
            return {
                "confirmed": True,
                "appointment_id": appointment.id,
                "calendar_url": calendar_url,
                "google_meet_link": appointment.meeting_link,
                "lead_name": lead.name,
                "lead_email": lead.email,
                "message": f"✓ {meeting_type.capitalize()} scheduled! Google Meet: {appointment.meeting_link}"
            }
        except Exception as e:
            return {
                "confirmed": False,
                "error": f"Failed to book meeting: {str(e)}"
            }

@tool
def cancel_meeting(appointment_id: int, reason: str = "") -> dict:
    """
    Cancel a scheduled meeting (DETERMINISTIC TOOL).
    
    Args:
        appointment_id: ID of the appointment to cancel
        reason: Reason for cancellation
    
    Returns:
        {"cancelled": bool, "message": str}
    """
    with Session(engine) as session:
        appointment = session.get(Appointment, appointment_id)
        
        if not appointment:
            return {"cancelled": False, "error": f"Appointment {appointment_id} not found"}
        
        try:
            appointment.status = "cancelled"
            appointment.notes = f"Cancelled: {reason}" if reason else "Cancelled"
            session.add(appointment)
            session.commit()
            
            return {
                "cancelled": True,
                "message": f"✓ Appointment {appointment_id} cancelled"
            }
        except Exception as e:
            return {
                "cancelled": False,
                "error": f"Failed to cancel meeting: {str(e)}"
            }
