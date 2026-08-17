"""Google OAuth handlers."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session
from database import get_session
from auth import get_current_active_user

router = APIRouter(prefix="/auth/google", tags=["oauth"])

# Import from parent auth.py (to be implemented)
# These functions will be moved here in full refactoring
# For now, this is a placeholder structure

@router.get("/status")
async def google_status(
    request: Request,
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Get Google OAuth connection status."""
    # Implementation moved from auth.py
    pass

@router.get("/url")
async def google_auth_url(
    request: Request,
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Get Google OAuth authorization URL."""
    pass

@router.get("/callback")
async def google_callback(
    request: Request,
    session: Session = Depends(get_session)
):
    """Handle Google OAuth callback."""
    pass

@router.post("/disconnect")
async def google_disconnect(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Disconnect Google OAuth."""
    pass
