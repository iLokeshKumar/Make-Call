import random
import uuid
from datetime import timedelta, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from database import get_session
from models.models import User, UserCreate, Token, MFAVerify, MFADisableRequest, ResendVerification, RevealOTPVerify, UserUpdate
from services.user_service import save_avatar
from auth import (
    verify_password, create_access_token, get_password_hash,
    get_current_active_user, generate_mfa_secret, get_mfa_provisioning_uri,
    generate_mfa_qr_base64, verify_mfa_token, ACCESS_TOKEN_EXPIRE_MINUTES
)
from email_service import send_smtp_email, get_styled_html

router = APIRouter(tags=["Authentication"])

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    mfa_token: Optional[str] = None,
    session: Session = Depends(get_session)
):
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.email_verified:
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="EMAIL_UNVERIFIED"
         )
    
    if user.mfa_enabled:
        if not mfa_token:
             return JSONResponse(status_code=403, content={"detail": "MFA_REQUIRED"})
        if not verify_mfa_token(user.mfa_secret, mfa_token):
             raise HTTPException(status_code=401, detail="Invalid MFA token")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/auth/mfa/setup")
async def setup_mfa(current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")
    
    secret = generate_mfa_secret()
    current_user.mfa_secret = secret
    session.add(current_user)
    session.commit()
    
    uri = get_mfa_provisioning_uri(current_user.username, secret)
    qr_code = generate_mfa_qr_base64(uri)
    
    return {"secret": secret, "qr_code": qr_code}

@router.post("/auth/mfa/enable")
async def enable_mfa(verify: MFAVerify, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    if not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up")
    
    if verify_mfa_token(current_user.mfa_secret, verify.token):
        current_user.mfa_enabled = True
        session.add(current_user)
        session.commit()

        # Send Confirmation Email
        subject = "Rio CRM: Two-Factor Authentication Enabled"
        email_body = f"Hello {current_user.username},\n\nTwo-Factor Authentication (2FA) has been successfully enabled on your account."
        styled_html = get_styled_html(
            "MFA Enabled Successfully",
            "Your account is now protected with 2FA.<br><br>You will be required to enter a code from your authenticator app every time you log in.",
            current_user.username
        )
        send_smtp_email(current_user.email, subject, email_body, styled_html)

        return {"message": "MFA enabled successfully"}

@router.post("/auth/mfa/request-disable")
async def request_mfa_disable(current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    current_user.mfa_disable_otp = otp
    session.add(current_user)
    session.commit()

    subject = "Rio CRM: OTP to disable Two-Factor Authentication"
    email_body = f"Hello {current_user.username},\n\nYour OTP to disable Two-Factor Authentication is: {otp}"
    styled_html = get_styled_html(
        "MFA Disable OTP",
        f"You have requested to disable 2FA on your account. Your verification code is:<br><br><span style='font-size: 24px; font-weight: bold; color: #7c3aed; letter-spacing: 5px;'>{otp}</span>",
        current_user.username
    )
    
    send_smtp_email(current_user.email, subject, email_body, styled_html)
    
    return {"message": "OTP sent to your registered email"}

@router.post("/auth/mfa/disable")
async def verify_mfa_disable(request: MFADisableRequest, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    
    if not current_user.mfa_disable_otp or request.token != current_user.mfa_disable_otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_disable_otp = None
    session.add(current_user)
    session.commit()

    subject = "Rio CRM: Two-Factor Authentication Disabled"
    email_body = f"Hello {current_user.username},\n\nTwo-Factor Authentication (2FA) has been successfully disabled on your account."
    styled_html = get_styled_html(
        "MFA Disabled Successfully",
        "Two-Factor Authentication has been removed from your account.",
        current_user.username
    )
    send_smtp_email(current_user.email, subject, email_body, styled_html)
    
    return {"message": "MFA disabled successfully"}

@router.delete("/auth/me")
async def delete_my_account(current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    user_email = current_user.email
    user_name = current_user.username
    user_role = current_user.role

    subject = "Your Rio CRM Account has been Deleted"
    email_body = f"Hello {user_name},\n\nYour account has been successfully deleted from Rio CRM."
    styled_html = get_styled_html(
        subject, 
        f"Your account with the role <strong>{user_role}</strong> has been successfully removed from our system.", 
        user_name
    )
    
    send_smtp_email(user_email, subject, email_body, styled_html)

    session.delete(current_user)
    session.commit()
    return {"message": "Account successfully deleted"}

@router.post("/register", response_model=User)
async def register_user(user: UserCreate, session: Session = Depends(get_session)):
    existing_user_name = session.exec(select(User).where(User.username == user.username)).first()
    if existing_user_name:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    existing_user_email = session.exec(select(User).where(User.email == user.email)).first()
    if existing_user_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    verification_token = str(uuid.uuid4())
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        is_active=True,
        email_verified=False,
        verification_token=verification_token
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    verify_link = f"http://localhost:3006/verify?token={verification_token}"
    email_body = f"Welcome to Rio CRM! Please verify your email by clicking the link below:\n\n{verify_link}"
    styled_html = get_styled_html("Verify Your Email", f"Please click the button below to verify your account.<br><br><a href='{verify_link}' class='btn' style='color: white;'>Verify Email</a>", db_user.username)
    
    send_smtp_email(db_user.email, "Verify Your Rio CRM Account", email_body, styled_html)

    return db_user

@router.get("/verify")
async def verify_email(token: str, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.verification_token == token)).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    
    user.email_verified = True
    user.verification_token = None
    session.add(user)
    session.commit()
    return {"message": "Email verified successfully."}

@router.post("/auth/resend-verification")
async def resend_verification(data: ResendVerification, session: Session = Depends(get_session)):
    user = None
    if data.email:
        user = session.exec(select(User).where(User.email == data.email)).first()
    elif data.username:
        user = session.exec(select(User).where(User.username == data.username)).first()
    
    if not user or user.email_verified:
        return {"message": "If the account exists and is not verified, a new link has been sent."}
    
    verification_token = str(uuid.uuid4())
    user.verification_token = verification_token
    session.add(user)
    session.commit()

    verify_link = f"http://localhost:3006/verify?token={verification_token}"
    email_body = f"Click here to verify your account: {verify_link}"
    styled_html = get_styled_html("Verify Your Email", f"You requested a new verification link.<br><br><a href='{verify_link}' class='btn' style='color: white;'>Verify Email</a>", user.username)
    
    send_smtp_email(user.email, "New Verification Link - Rio CRM", email_body, styled_html)
    
    return {"message": "New verification link sent."}

@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

@router.patch("/users/me", response_model=User)
async def update_users_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    update_data = user_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)
    
    current_user.updated_at = datetime.now(timezone.utc)
    current_user.updated_by = current_user.username
    
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user

@router.post("/auth/reveal/request")
async def request_reveal_otp(current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    current_user.reveal_otp = otp
    current_user.reveal_otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    session.add(current_user)
    session.commit()

    subject = "Rio CRM: OTP for Data Reveal"
    email_body = f"Hello {current_user.username},\n\nYour OTP to reveal sensitive data is: {otp}"
    styled_html = get_styled_html(
        "Data Reveal OTP",
        f"You have requested to reveal sensitive contact information. Your verification code is:<br><br><span style='font-size: 24px; font-weight: bold; color: #7c3aed; letter-spacing: 5px;'>{otp}</span>",
        current_user.username
    )
    
    send_smtp_email(current_user.email, subject, email_body, styled_html)
    
    return {"message": "OTP sent to your registered email"}

@router.post("/auth/reveal/verify")
async def verify_reveal_otp(verify: RevealOTPVerify, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    if not current_user.reveal_otp or verify.token != current_user.reveal_otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    if current_user.reveal_otp_expires_at and datetime.now(timezone.utc).replace(tzinfo=None) > current_user.reveal_otp_expires_at.replace(tzinfo=None):
         # Note: SQLModel might return naive datetimes or offset-aware depending on DB. 
         # Best to normalize. I'll use timezone.utc throughout.
         pass

    # Re-comparing properly with timezone awareness
    now = datetime.now(timezone.utc)
    # Ensure reveal_otp_expires_at is timezone-aware if it's not
    expires_at = current_user.reveal_otp_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at and now > expires_at:
        raise HTTPException(status_code=400, detail="OTP expired")
    
    # Clear the OTP after successful verification
    current_user.reveal_otp = None
    current_user.reveal_otp_expires_at = None
    session.add(current_user)
    session.commit()
    
    return {"message": "Verification successful", "email": current_user.email, "phone_number": current_user.phone_number}

@router.post("/auth/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """Uploads a user avatar and updates the profile picture URL."""
    try:
        url = save_avatar(file)
        current_user.profile_picture_url = f"http://localhost:6060{url}"
        session.add(current_user)
        session.commit()
        session.refresh(current_user)
        return {"url": current_user.profile_picture_url}
    except Exception as e:
        logger.error(f"❌ Avatar Upload Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload avatar")
