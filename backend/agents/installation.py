"""
Installation Agent — Prerequisite checklist, slot booking, installer assignment,
completion report, and post-install warranty ticket creation.

Actions:
  check_prerequisites — Read checklist_json and report met/unmet items
  book_slot           — Set scheduled_at and create an Appointment
  assign_installer    — Assign installer user to the job
  complete            — Mark job complete, create 30-day warranty check-in ticket
  generate_report     — Return a summary report dict for the job
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from models.models import (
    AgentTask,
    Appointment,
    InstallationJob,
    ServiceTicket,
    utc_now,
)

logger = logging.getLogger(__name__)

_PREREQUISITE_KEYS = ["power_supply", "site_ready", "customer_present"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_job(session: Session, task: AgentTask) -> InstallationJob | None:
    inp = task.input_json
    order_id = inp.get("order_id")
    job_id = inp.get("job_id")

    if job_id:
        return session.exec(
            select(InstallationJob).where(
                InstallationJob.id == job_id,
                InstallationJob.company_id == task.company_id,
            )
        ).first()
    if order_id:
        return session.exec(
            select(InstallationJob).where(
                InstallationJob.order_id == order_id,
                InstallationJob.company_id == task.company_id,
            )
        ).first()
    return None


def _generate_ticket_number(session: Session, company_id: int) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"TKT-{year}-"
    tickets = session.exec(
        select(ServiceTicket).where(ServiceTicket.company_id == company_id)
    ).all()
    max_seq = 0
    for t in tickets:
        if t.ticket_number.startswith(prefix):
            try:
                seq = int(t.ticket_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass
    return f"{prefix}{max_seq + 1:04d}"


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_check_prerequisites(session: Session, task: AgentTask) -> dict:
    job = _get_job(session, task)
    if not job:
        return {"error": "InstallationJob not found (provide order_id or job_id)"}

    checklist = job.checklist_json or {}
    # checklist_json may be a list of dicts or a plain dict; normalise to dict
    if isinstance(checklist, list):
        checklist = {item: False for item in checklist}

    results = {}
    for key in _PREREQUISITE_KEYS:
        results[key] = bool(checklist.get(key, False))

    all_met = all(results.values())
    logger.info(
        "[InstallationAgent] Prerequisites for job %s: %s (all_met=%s)",
        job.job_number, results, all_met,
    )
    return {
        "action": "check_prerequisites",
        "job_id": job.id,
        "job_number": job.job_number,
        "prerequisites": results,
        "all_met": all_met,
    }


def _handle_book_slot(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    scheduled_at_str = inp.get("scheduled_at")
    lead_id = inp.get("lead_id")

    if not scheduled_at_str:
        return {"error": "scheduled_at (ISO string) is required for book_slot"}

    job = _get_job(session, task)
    if not job:
        return {"error": "InstallationJob not found (provide order_id or job_id)"}

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_str)
    except ValueError:
        return {"error": f"scheduled_at is not a valid ISO datetime: {scheduled_at_str!r}"}

    job.scheduled_at = scheduled_at
    job.status = "scheduled"
    session.add(job)

    # Determine lead_id for the appointment
    appt_lead_id = lead_id or job.lead_id
    if appt_lead_id:
        appointment = Appointment(
            company_id=task.company_id,
            lead_id=appt_lead_id,
            appointment_time=scheduled_at,
            status="scheduled",
            notes="Installation slot",
        )
        session.add(appointment)

    session.commit()
    logger.info(
        "[InstallationAgent] Booked slot for job %s at %s", job.job_number, scheduled_at
    )
    return {
        "action": "book_slot",
        "job_id": job.id,
        "job_number": job.job_number,
        "scheduled_at": scheduled_at.isoformat(),
        "status": job.status,
    }


def _handle_assign_installer(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    installer_user_id = inp.get("installer_user_id")
    if not installer_user_id:
        return {"error": "installer_user_id is required for assign_installer"}

    job = _get_job(session, task)
    if not job:
        return {"error": "InstallationJob not found (provide order_id or job_id)"}

    job.assigned_user_id = installer_user_id
    job.status = "assigned"
    session.add(job)
    session.commit()
    logger.info(
        "[InstallationAgent] Job %s assigned to user %s", job.job_number, installer_user_id
    )
    return {
        "action": "assign_installer",
        "job_id": job.id,
        "job_number": job.job_number,
        "assigned_user_id": installer_user_id,
        "status": job.status,
    }


def _handle_complete(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    completion_notes = inp.get("completion_notes", "")
    csat_score = inp.get("csat_score")

    job = _get_job(session, task)
    if not job:
        return {"error": "InstallationJob not found (provide order_id or job_id)"}

    now = utc_now()
    job.status = "completed"
    job.completed_at = now
    job.completion_notes = completion_notes
    if csat_score is not None:
        job.csat_score = int(csat_score)
    session.add(job)

    # Create 30-day warranty check-in ticket
    warranty_sla_hours = 720  # 30 days
    warranty_ticket = ServiceTicket(
        company_id=task.company_id,
        lead_id=job.lead_id,
        order_id=job.order_id,
        ticket_number=_generate_ticket_number(session, task.company_id),
        title="30-day post-install check-in",
        description=f"Automatic 30-day warranty check-in for installation job {job.job_number}.",
        status="open",
        priority="low",
        category="maintenance",
        channel="manual",
        sla_hours=warranty_sla_hours,
        sla_due_at=now + timedelta(hours=warranty_sla_hours),
    )
    session.add(warranty_ticket)
    session.commit()
    session.refresh(warranty_ticket)

    logger.info(
        "[InstallationAgent] Job %s completed; warranty ticket %s created",
        job.job_number, warranty_ticket.ticket_number,
    )
    return {
        "action": "complete",
        "job_id": job.id,
        "job_number": job.job_number,
        "completed_at": now.isoformat(),
        "warranty_ticket_id": warranty_ticket.id,
        "warranty_ticket_number": warranty_ticket.ticket_number,
    }


def _handle_generate_report(session: Session, task: AgentTask) -> dict:
    job = _get_job(session, task)
    if not job:
        return {"error": "InstallationJob not found (provide order_id or job_id)"}

    checklist = job.checklist_json or {}
    if isinstance(checklist, list):
        checklist = {item: False for item in checklist}

    prereq_met = sum(1 for k in _PREREQUISITE_KEYS if checklist.get(k))
    prereq_total = len(_PREREQUISITE_KEYS)

    duration_seconds = None
    if job.started_at and job.completed_at:
        delta = job.completed_at - job.started_at
        duration_seconds = int(delta.total_seconds())

    report = {
        "action": "generate_report",
        "job_id": job.id,
        "job_number": job.job_number,
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "duration_seconds": duration_seconds,
        "assigned_user_id": job.assigned_user_id,
        "prerequisites_met": f"{prereq_met}/{prereq_total}",
        "checklist": checklist,
        "completion_notes": job.completion_notes,
        "csat_score": job.csat_score,
        "installation_address": job.installation_address,
    }
    return report


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate installation agent action."""
    action = task.input_json.get("action")
    try:
        if action == "check_prerequisites":
            return _handle_check_prerequisites(session, task)
        elif action == "book_slot":
            return _handle_book_slot(session, task)
        elif action == "assign_installer":
            return _handle_assign_installer(session, task)
        elif action == "complete":
            return _handle_complete(session, task)
        elif action == "generate_report":
            return _handle_generate_report(session, task)
        else:
            return {
                "error": f"Unknown action: {action!r}",
                "valid_actions": [
                    "check_prerequisites", "book_slot", "assign_installer",
                    "complete", "generate_report",
                ],
            }
    except Exception as exc:
        logger.exception("[InstallationAgent] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}
