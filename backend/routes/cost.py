import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import User, ProviderRateCreate, ProviderRateUpdate
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
    rate = get_live_rate(from_currency.upper(), to_currency.upper(), session=session, company_id=current_user.company_id)
    return {
        "from": from_currency.upper(),
        "to": to_currency.upper(),
        "rate": rate,
    }


@router.get("/rates")
def list_provider_rates(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all custom provider rates configured for the company."""
    from sqlmodel import select
    from models.models import ProviderRate
    stmt = select(ProviderRate).where(ProviderRate.company_id == current_user.company_id)
    return session.exec(stmt).all()


@router.post("/rates")
def create_or_update_provider_rate(
    payload: ProviderRateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create or update a provider rate for the company."""
    from sqlmodel import select
    from models.models import ProviderRate
    import datetime
    
    stmt = select(ProviderRate).where(
        ProviderRate.company_id == current_user.company_id,
        ProviderRate.category == payload.category,
        ProviderRate.provider == payload.provider,
        ProviderRate.model_or_voice == payload.model_or_voice,
    )
    existing = session.exec(stmt).first()
    if existing:
        existing.rate_per_second = payload.rate_per_second
        existing.is_active = payload.is_active
        existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    else:
        new_rate = ProviderRate(
            company_id=current_user.company_id,
            category=payload.category,
            provider=payload.provider,
            model_or_voice=payload.model_or_voice,
            rate_per_second=payload.rate_per_second,
            is_active=payload.is_active,
        )
        session.add(new_rate)
        session.commit()
        session.refresh(new_rate)
        return new_rate


@router.delete("/rates/{rate_id}")
def delete_provider_rate(
    rate_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a provider rate for the company."""
    from fastapi import HTTPException, status
    from models.models import ProviderRate
    
    rate = session.get(ProviderRate, rate_id)
    if not rate or rate.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider rate not found."
        )
    session.delete(rate)
    session.commit()
    return {"success": True}

