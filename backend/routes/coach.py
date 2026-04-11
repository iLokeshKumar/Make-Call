from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import User

router = APIRouter(prefix="/crm", tags=["CRM"])


@router.get("/coach/scores")
async def list_coach_scores(
    limit: int = Query(default=20, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the most recent AI coach scores for the company."""
    from services.call_coach_service import get_recent_coach_scores
    scores = get_recent_coach_scores(session, current_user.company_id, limit)
    return {"items": scores}


@router.get("/coach/averages")
async def get_coach_averages_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate performance averages across all scored calls."""
    from services.call_coach_service import get_coach_averages
    return get_coach_averages(session, current_user.company_id)


@router.get("/coach/scores/{interaction_id}")
async def get_coach_score_for_interaction_route(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from services.call_coach_service import get_coach_score_for_interaction
    score = get_coach_score_for_interaction(session, current_user.company_id, interaction_id)
    return score  # None serialises as JSON null — frontend checks for null
