from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import Lead, User

router = APIRouter(prefix="/crm", tags=["CRM"])


class CounterScriptUpsert(SQLModel):
    competitor_name: str
    counter_script: str


@router.get("/competitors/summary")
async def get_competitor_summary_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return aggregated mention counts per competitor for the company."""
    from services.competitor_service import get_competitor_summary
    return get_competitor_summary(session, current_user.company_id)


@router.get("/leads/{lead_id}/competitors")
async def get_lead_competitor_mentions(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all competitor mentions detected on calls with this lead."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    from services.competitor_service import get_competitor_mentions_for_lead
    mentions = get_competitor_mentions_for_lead(session, current_user.company_id, lead_id)
    return {"lead_id": lead_id, "lead_name": lead.name, "items": mentions}


@router.post("/competitors/counter-script")
async def upsert_counter_script_route(
    data: CounterScriptUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Store or update the counter-script for a competitor."""
    from services.competitor_service import upsert_counter_script
    return upsert_counter_script(
        session=session,
        company_id=current_user.company_id,
        competitor_name=data.competitor_name,
        counter_script=data.counter_script,
        actor_user_id=current_user.id,
    )
