from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import User
from services.automation_worker_service import run_worker_cycle


router = APIRouter(prefix="/automation", tags=["Automation"])


@router.post("/run-cycle")
async def run_automation_cycle_route(
    dial_limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.launch")),
):
    return run_worker_cycle(
        session=session,
        company_id=current_user.company_id,
        dial_limit_per_company=dial_limit,
    )
