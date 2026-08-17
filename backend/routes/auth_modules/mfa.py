"""MFA (Multi-Factor Authentication) handlers."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from database import get_session
from auth import get_current_active_user

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

@router.post("/setup")
async def setup_mfa(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Generate MFA secret and QR code."""
    pass

@router.post("/enable")
async def enable_mfa(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Enable MFA after verifying code."""
    pass

@router.post("/disable/request")
async def request_mfa_disable(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Request MFA disable (sends email with code)."""
    pass

@router.post("/disable")
async def disable_mfa(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Disable MFA after verifying email code."""
    pass
