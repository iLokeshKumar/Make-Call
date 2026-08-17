"""User profile handlers."""
from fastapi import APIRouter, Depends, UploadFile, File
from sqlmodel import Session
from database import get_session
from auth import get_current_active_user

router = APIRouter(prefix="/auth/profile", tags=["profile"])

@router.get("/me")
async def get_me(current_user = Depends(get_current_active_user)):
    """Get current user profile."""
    pass

@router.patch("/me")
async def update_me(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Update current user profile."""
    pass

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Upload user avatar."""
    pass

@router.delete("/me")
async def delete_my_account(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Delete user account."""
    pass

@router.get("/company")
async def get_company_profile(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Get company profile."""
    pass

@router.patch("/company")
async def update_company_profile(
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Update company profile."""
    pass

@router.post("/company/logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user = Depends(get_current_active_user)
):
    """Upload company logo."""
    pass
