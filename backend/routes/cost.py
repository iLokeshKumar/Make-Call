import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import User
from services.platform.cost_service import get_cost_breakdown, get_live_rate

router = APIRouter(prefix="/crm/cost", tags=["Cost Analytics"])
logger = logging.getLogger(__name__)


@router.get("/breakdown")
def cost_breakdown(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    agent_id: Optional[int] = Query(None),
    currency: str = Query("USD", description="Target currency code (e.g. USD, INR)"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Daily cost per minute breakdown for the company.
    Defaults to USD. Pass ?currency=INR for live-converted INR values."""
    return get_cost_breakdown(
        session, current_user.company_id,
        start_date=start_date, end_date=end_date, agent_id=agent_id,
        currency=currency,
    )


@router.get("/live-rate")
def live_rate(
    from_currency: str = Query("USD", max_length=10),
    to_currency: str = Query("INR", max_length=10),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Fetch the live exchange rate between two currencies using forex-python."""
    rate = get_live_rate(from_currency.upper(), to_currency.upper())
    return {
        "from": from_currency.upper(),
        "to": to_currency.upper(),
        "rate": rate,
    }
