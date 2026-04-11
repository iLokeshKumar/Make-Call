from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, func, select

from auth import get_current_user
from database import get_session
from models.models import ObjectionEntry, User, utc_now

router = APIRouter(prefix="/crm", tags=["CRM"])


class ObjectionCreate(SQLModel):
    objection_key: str
    objection_text: str
    category: str = "general"
    rebuttal: Optional[str] = None
    is_active: bool = True


class ObjectionUpdate(SQLModel):
    objection_text: Optional[str] = None
    category: Optional[str] = None
    rebuttal: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/objections")
async def list_objections(
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(ObjectionEntry).where(
        ObjectionEntry.company_id == current_user.company_id
    )
    count_query = select(func.count()).select_from(ObjectionEntry).where(
        ObjectionEntry.company_id == current_user.company_id
    )
    if category:
        query = query.where(ObjectionEntry.category == category)
        count_query = count_query.where(ObjectionEntry.category == category)
    if is_active is not None:
        query = query.where(ObjectionEntry.is_active == is_active)
        count_query = count_query.where(ObjectionEntry.is_active == is_active)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(ObjectionEntry.frequency_count.desc())
             .offset((page - 1) * limit)
             .limit(limit)
    ).all()
    return {"total": total, "page": page, "items": items}


@router.post("/objections")
async def create_objection(
    data: ObjectionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    key = data.objection_key.strip().lower()
    existing = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.company_id == current_user.company_id,
            ObjectionEntry.objection_key == key,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Objection key already exists for this company")

    entry = ObjectionEntry(
        company_id=current_user.company_id,
        objection_key=key,
        objection_text=data.objection_text.strip(),
        category=data.category,
        rebuttal=data.rebuttal,
        is_active=data.is_active,
        frequency_count=0,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.patch("/objections/{objection_id}")
async def update_objection(
    objection_id: int,
    data: ObjectionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    entry = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.id == objection_id,
            ObjectionEntry.company_id == current_user.company_id,
        )
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Objection not found")

    if data.objection_text is not None:
        entry.objection_text = data.objection_text.strip()
    if data.category is not None:
        entry.category = data.category
    if data.rebuttal is not None:
        entry.rebuttal = data.rebuttal
    if data.is_active is not None:
        entry.is_active = data.is_active

    entry.updated_at = utc_now()
    entry.updated_by = current_user.id
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/objections/{objection_id}", status_code=204)
async def delete_objection(
    objection_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    entry = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.id == objection_id,
            ObjectionEntry.company_id == current_user.company_id,
        )
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Objection not found")
    session.delete(entry)
    session.commit()
