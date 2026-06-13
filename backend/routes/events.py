import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session, engine
from models.models import CallAudioEvent, User, utc_now
from services.voice.event_injection_service import (
    get_active_calls, inject_event, register_pipeline, unregister_pipeline,
)

router = APIRouter(prefix="/crm/events", tags=["Events"])
logger = logging.getLogger(__name__)


@router.post("/inject")
async def inject_call_event(
    interaction_id: int = Query(...),
    event_type: str = Query(...),
    payload: dict = {},
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Inject an event into an active call."""
    from models.models import EventInjectionRequest
    req = EventInjectionRequest(
        interaction_id=interaction_id,
        event_type=event_type,
        payload=payload,
    )
    try:
        result = await inject_event(session, current_user.company_id, req)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/active-calls")
def list_active_calls(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_active_calls(current_user.company_id)


async def _event_poll_loop(websocket: WebSocket, company_id: int, last_id: int):
    """Poll new CallAudioEvent rows for the company and push to WS."""
    idle_ticks = 0
    try:
        while True:
            with Session(engine) as s:
                rows = s.exec(
                    select(CallAudioEvent)
                    .where(CallAudioEvent.company_id == company_id)
                    .where(CallAudioEvent.id > last_id)
                    .order_by(CallAudioEvent.id)
                    .limit(20)
                ).all()
            if rows:
                for row in rows:
                    await websocket.send_json({
                        "type": "event_status",
                        "event_id": row.id,
                        "interaction_id": row.interaction_id,
                        "event_type": row.event_type,
                        "status": row.status,
                        "ts": row.created_at.isoformat(),
                    })
                    last_id = row.id
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 150 == 0:
                    await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.2)
    except Exception:
        pass


@router.websocket("/ws/{company_id}")
async def event_monitor_ws(websocket: WebSocket, company_id: int):
    """WebSocket: stream event injection status for a company."""
    await websocket.accept()
    last_id = 0
    await _event_poll_loop(websocket, company_id, last_id)
