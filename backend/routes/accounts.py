from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, func, select

from auth import get_current_user
from services.core.auth_service import user_has_any_permission
from database import get_session
from models.models import Account, Lead, User, utc_now

router = APIRouter(prefix="/crm", tags=["CRM"])


class AccountCreate(SQLModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    employee_count: Optional[int] = None
    notes: Optional[str] = None
    is_active: bool = True


class AccountUpdate(SQLModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    employee_count: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/accounts")
async def list_accounts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Account).where(Account.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Account).where(Account.company_id == current_user.company_id)

    # Sales reps only see accounts that have leads assigned to them
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    if not can_read_company:
        user_account_ids = select(Lead.account_id).where(
            Lead.company_id == current_user.company_id,
            Lead.owner_user_id == current_user.id,
            Lead.account_id.is_not(None),
            Lead.deleted_at.is_(None),
        ).distinct()
        query = query.where(Account.id.in_(user_account_ids))
        count_query = count_query.where(Account.id.in_(user_account_ids))

    if search:
        like = f"%{search}%"
        query = query.where(Account.name.ilike(like))
        count_query = count_query.where(Account.name.ilike(like))

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Account.name).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.post("/accounts", response_model=Account)
async def create_account(
    data: AccountCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = Account(
        company_id=current_user.company_id,
        name=data.name.strip(),
        industry=data.industry,
        website=data.website,
        city=data.city,
        state=data.state,
        country=data.country,
        employee_count=data.employee_count,
        notes=data.notes,
        is_active=data.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.put("/accounts/{account_id}", response_model=Account)
async def update_account(
    account_id: int,
    data: AccountUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = session.exec(
        select(Account).where(Account.id == account_id, Account.company_id == current_user.company_id)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)

    account.updated_at = utc_now()
    account.updated_by = current_user.id
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = session.exec(
        select(Account).where(Account.id == account_id, Account.company_id == current_user.company_id)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    session.delete(account)
    session.commit()
    return {"message": "Account deleted"}
