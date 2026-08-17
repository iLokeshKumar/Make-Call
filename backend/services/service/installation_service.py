from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    InstallationJob,
    InstallationJobCreate,
    utc_now,
)

logger = logging.getLogger(__name__)

VALID_JOB_STATUSES = {
    "scheduled",
    "prerequisite_check",
    "assigned",
    "in_progress",
    "completed",
    "failed",
}


def _generate_job_number(session: Session, company_id: int) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"INS-{year}-"
    jobs = session.exec(
        select(InstallationJob).where(InstallationJob.company_id == company_id)
    ).all()
    max_seq = 0
    for j in jobs:
        if j.job_number.startswith(prefix):
            try:
                seq = int(j.job_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass
    return f"{prefix}{max_seq + 1:04d}"


def create_installation_job(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: InstallationJobCreate,
) -> InstallationJob:
    now = utc_now()
    job = InstallationJob(
        company_id=company_id,
        order_id=data.order_id,
        lead_id=data.lead_id,
        ticket_id=data.ticket_id,
        job_number=_generate_job_number(session, company_id),
        status="scheduled",
        scheduled_at=data.scheduled_at,
        installation_address=data.installation_address,
        checklist_json=data.checklist_json,
        prerequisites_met=False,
        created_by=actor_user_id,
        updated_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job_or_404(session: Session, company_id: int, job_id: int) -> InstallationJob:
    job = session.exec(
        select(InstallationJob).where(
            InstallationJob.id == job_id,
            InstallationJob.company_id == company_id,
        )
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Installation job not found")
    return job


def list_jobs(
    session: Session,
    company_id: int,
    status: Optional[str] = None,
    order_id: Optional[int] = None,
    assigned_user_id: Optional[int] = None,
) -> list[InstallationJob]:
    query = select(InstallationJob).where(InstallationJob.company_id == company_id)
    if status:
        query = query.where(InstallationJob.status == status)
    if order_id:
        query = query.where(InstallationJob.order_id == order_id)
    if assigned_user_id:
        query = query.where(InstallationJob.assigned_user_id == assigned_user_id)
    return session.exec(query.order_by(InstallationJob.created_at.desc())).all()


def update_job_status(
    session: Session,
    company_id: int,
    actor_user_id: int,
    job_id: int,
    status: str,
    notes: Optional[str] = None,
) -> InstallationJob:
    if status not in VALID_JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_JOB_STATUSES))}",
        )

    job = get_job_or_404(session, company_id, job_id)
    now = utc_now()
    job.status = status
    job.updated_at = now
    job.updated_by = actor_user_id

    if status == "in_progress" and job.started_at is None:
        job.started_at = now

    if notes:
        job.completion_notes = notes

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def check_prerequisites(
    session: Session,
    company_id: int,
    job_id: int,
) -> tuple[bool, list[str]]:
    """Check checklist_json for unmet items. Returns (all_met, unmet_list)."""
    job = get_job_or_404(session, company_id, job_id)

    if not job.checklist_json:
        return True, []

    unmet: list[str] = []
    for item in job.checklist_json:
        # Each checklist item is expected to be a dict with at least {"name": ..., "done": bool}
        # or a plain string (treat as unmet)
        if isinstance(item, dict):
            if not item.get("done", False):
                unmet.append(item.get("name", str(item)))
        else:
            # Plain string items are considered unmet by default
            unmet.append(str(item))

    all_met = len(unmet) == 0

    # Update prerequisites_met flag on the job
    if job.prerequisites_met != all_met:
        job.prerequisites_met = all_met
        job.updated_at = utc_now()
        session.add(job)
        session.commit()

    return all_met, unmet


def complete_job(
    session: Session,
    company_id: int,
    actor_user_id: int,
    job_id: int,
    completion_notes: Optional[str] = None,
    photos_json: Optional[list] = None,
    csat_score: Optional[int] = None,
) -> InstallationJob:
    job = get_job_or_404(session, company_id, job_id)
    now = utc_now()

    job.status = "completed"
    job.completed_at = now
    job.updated_at = now
    job.updated_by = actor_user_id

    if completion_notes is not None:
        job.completion_notes = completion_notes
    if photos_json is not None:
        job.photos_json = photos_json
    if csat_score is not None:
        if not (1 <= csat_score <= 5):
            raise HTTPException(status_code=400, detail="CSAT score must be between 1 and 5")
        job.csat_score = csat_score

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def assign_installer(
    session: Session,
    company_id: int,
    actor_user_id: int,
    job_id: int,
    user_id: int,
) -> InstallationJob:
    job = get_job_or_404(session, company_id, job_id)
    job.assigned_user_id = user_id
    job.updated_at = utc_now()
    job.updated_by = actor_user_id
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
