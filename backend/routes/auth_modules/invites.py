"""User invitation handlers."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from database import get_session
from auth import get_current_active_user

router = APIRouter(prefix="/auth/invites", tags=["invites"])

@router.post("/")
async def create_invite(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Create user invitation."""
    pass

@router.get("/{token}")
async def get_invite_info(
    token: str,
    session: Session = Depends(get_session)
):
    """Get invitation details by token."""
    pass

@router.post("/{token}/accept")
async def accept_invite(
    token: str,
    session: Session = Depends(get_session)
):
    """Accept invitation and create account."""
    pass
