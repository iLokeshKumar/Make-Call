from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import OrderCreate, OrderStatusUpdate, User
from services.order.order_service import (
    cancel_order,
    create_order,
    create_order_from_quote,
    get_order_or_404,
    list_orders,
    update_order_status,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("")
async def create_order_route(
    data: OrderCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.manage")),
):
    return create_order(session, current_user.company_id, current_user.id, data)


@router.post("/from-quote/{quote_id}")
async def create_order_from_quote_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.manage")),
):
    return create_order_from_quote(session, current_user.company_id, current_user.id, quote_id)


@router.get("")
async def list_orders_route(
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.read")),
):
    return list_orders(session, current_user.company_id, status=status, lead_id=lead_id)


@router.get("/{order_id}")
async def get_order_route(
    order_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.read")),
):
    return get_order_or_404(session, current_user.company_id, order_id)


@router.patch("/{order_id}/status")
async def update_order_status_route(
    order_id: int,
    data: OrderStatusUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.manage")),
):
    return update_order_status(
        session,
        current_user.company_id,
        current_user.id,
        order_id,
        data.status,
        notes=data.notes,
    )


class CancelOrderRequest(OrderStatusUpdate):
    reason: str


@router.delete("/{order_id}")
async def cancel_order_route(
    order_id: int,
    data: CancelOrderRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("order.manage")),
):
    return cancel_order(
        session,
        current_user.company_id,
        current_user.id,
        order_id,
        reason=data.reason,
    )
