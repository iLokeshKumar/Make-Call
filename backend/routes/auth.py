import secrets
import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, select
from typing import Optional

import os
import json
import requests

from auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    PermissionChecker,
    create_access_token,
    generate_mfa_qr_base64,
    generate_mfa_secret,
    get_current_active_user,
    get_current_user,
    get_mfa_provisioning_uri,
    get_password_hash,
    verify_mfa_token,
    verify_password,
)
from credentials_service import get_company_credential

from database import get_session
from models.models import (
    Company,
    CompanyRegister,
    Invite,
    InviteAccept,
    InviteCreate,
    Role,
    Token,
    User,
    CompanySetting,
    UserRole,
    LoginHistory,
    utc_now,
)
from email_service import get_styled_html, send_smtp_email
from google_auth_oauthlib.flow import Flow
from utils.url_utils import normalize_base_url
from services.auth_service import (
    create_default_permissions,
    create_default_roles_for_company,
    seed_default_role_permissions,
)


def _generate_verification_token(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    session.add(user)
    session.commit()
    return token


def _send_verification_email(user: User, token: str, company_name: str) -> None:
    domain = os.getenv("DOMAIN", "localhost:3006")
    verification_url = f"https://{domain}/auth/verify-email?token={token}"
    subject = "Verify your Rio CRM account"
    body = (
        f"Hi {user.first_name or user.email},\n\n"
        "Thanks for creating a Rio CRM account. Please verify your email address by clicking the button below.\n\n"
        f"If the button doesn't work, paste this link into your browser: {verification_url}\n\n"
        "If you did not create this account, please ignore this message."
    )
    html_body = get_styled_html(
        subject=subject,
        body="Thanks for creating a Rio CRM account. Click the button below to verify your email address.",
        lead_name=user.first_name or "valued customer",
        company_name=company_name,
        company_website=f"https://{domain}/",
        cta_url=verification_url,
        cta_label="Verify Email Address",
    )
    send_smtp_email(
        to_email=user.email,
        subject=subject,
        body=body,
        html_body=html_body,
    )


logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", os.path.join(os.getcwd(), "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _get_user_role(session: Session, user_id: int) -> str:
    role_name = (
        session.exec(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .limit(1)
        )
        .first()
    )
    return role_name or "sales_representative"


BASE_DIR = Path(__file__).resolve().parents[1]
GOOGLE_CREDENTIALS_PATH = BASE_DIR / "google_credentials.json"
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3006/profile")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
GOOGLE_STATE_CACHE: dict[int, str] = {}


def _serialize_user(session: Session, user: User) -> dict:
    payload = user.model_dump()
    payload["role"] = _get_user_role(session, user.id)
    company = session.get(Company, user.company_id)
    if company:
        payload["company_name"] = company.name
        payload["company_website"] = company.website
        payload["company_slug"] = company.slug
        payload["company_domain"] = company.domain
    return payload


def _load_google_client_config() -> dict:
    if not GOOGLE_CREDENTIALS_PATH.exists():
        raise RuntimeError("Google credentials file is missing")
    return json.loads(GOOGLE_CREDENTIALS_PATH.read_text(encoding="utf-8"))


def _get_google_flow() -> Flow:
    config = _load_google_client_config()
    return Flow.from_client_config(config, scopes=GOOGLE_SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)


def _upsert_company_setting(
    session: Session,
    company_id: int,
    key: str,
    value: str | None,
    user_id: int,
    is_secret: bool = False,
):
    if value is None:
        return
    existing = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == company_id, CompanySetting.key == key)
    ).first()
    if existing:
        existing.value = value
        existing.is_secret = is_secret
        existing.updated_by = user_id
        existing.updated_at = utc_now()
        session.add(existing)
    else:
        session.add(
            CompanySetting(
                company_id=company_id,
                key=key,
                value=value,
                is_secret=is_secret,
                created_by=user_id,
                updated_by=user_id,
            )
        )


def _get_company_setting_value(session: Session, company_id: int, key: str) -> str | None:
    setting = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == company_id, CompanySetting.key == key)
    ).first()
    return setting.value if setting else None


def _delete_company_setting(session: Session, company_id: int, key: str):
    setting = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == company_id, CompanySetting.key == key)
    ).first()
    if setting:
        session.delete(setting)
        session.commit()


class GoogleAuthRequest(SQLModel):
    code: str
    state: Optional[str] = None


class CompanyProfileResponse(SQLModel):
    name: str
    slug: str
    domain: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    status: str
    subscription_tier: str
    max_users: int


class CompanyProfileUpdateRequest(SQLModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    domain: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    status: Optional[str] = None
    subscription_tier: Optional[str] = None
    max_users: Optional[int] = None


def _serialize_company(company: Company) -> CompanyProfileResponse:
    return CompanyProfileResponse(
        name=company.name,
        slug=company.slug,
        domain=company.domain,
        website=company.website,
        logo_url=company.logo_url,
        primary_color=company.primary_color,
        status=company.status,
        subscription_tier=company.subscription_tier,
        max_users=company.max_users,
    )


def _get_company_info(session: Session, user: User) -> tuple[str, str]:
    company = session.get(Company, user.company_id)
    if company:
        company_name = company.name
        company_website = company.website or f"https://{company.domain or company.slug or 'rio-crm.example.com'}"
        return company_name, company_website
    return "Rio CRM", "https://rio-crm.example.com/"


def _resolve_frontend_base(company: Company | None) -> str:
    candidate = (
        os.getenv("FRONTEND_BASE_URL")
        or company.website
        or company.domain
        or os.getenv("DOMAIN")
        or "localhost:3000"
    )
    return normalize_base_url(candidate, "https://localhost:3000")


def _send_invite_email(session: Session, company: Company | None, invite: Invite) -> None:
    company_name = company.name if company else "Rio CRM"
    company_website = company.website or f"https://{company.domain or company.slug or 'rio-crm.example.com'}" if company else "https://rio-crm.example.com/"
    base_url = _resolve_frontend_base(company)
    invite_url = f"{base_url}/invite/accept?token={invite.token}"

    subject = f"You're invited to join {company_name} on Rio CRM"
    body = (
        f"Hi,\n\n"
        f"You've been invited to join {company_name} on Rio CRM. "
        f"Click the button below to accept the invite and set up your account.\n\n"
        f"If the button doesn't work, paste this link into your browser: {invite_url}\n\n"
        "If you did not request this, please ignore this message."
    )
    html_body = get_styled_html(
        subject=subject,
        body=f"You've been invited to join <strong>{company_name}</strong> on Rio CRM.<br><br>"
             "Click the button below to accept your invitation and set up your account.",
        lead_name="Future teammate",
        company_name=company_name,
        company_website=company_website,
        cta_url=invite_url,
        cta_label="Accept Invitation &amp; Join",
    )

    smtp_host = get_company_credential(session, invite.company_id, "SMTP_HOST")
    smtp_port = get_company_credential(session, invite.company_id, "SMTP_PORT")
    smtp_username = get_company_credential(session, invite.company_id, "SMTP_USERNAME")
    smtp_password = get_company_credential(session, invite.company_id, "SMTP_PASSWORD")
    smtp_from_email = get_company_credential(session, invite.company_id, "SMTP_FROM_EMAIL")

    success = send_smtp_email(
        to_email=invite.email,
        subject=subject,
        body=body,
        html_body=html_body,
        company_name=company_name,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from_email=smtp_from_email,
    )

    if not success:
        logger.warning("Invite email could not be delivered for invite %s", invite.id)


def _send_reveal_code_email(user: User, company_name: str, company_website: str, code: str) -> None:
    subject = "Your Rio CRM account verification code"
    body = (
        f"Hi {user.first_name or user.username or user.email},\n\n"
        f"Use the code {code} to reveal your sensitive profile details. It expires in 10 minutes.\n"
        "If you did not request this, please contact your admin immediately."
    )
    html_body = get_styled_html(
        subject=subject,
        body=body,
        lead_name=user.first_name or user.username or "valued customer",
        company_name=company_name,
        company_website=company_website,
    )
    send_smtp_email(
        to_email=user.email,
        subject=subject,
        body=body,
        html_body=html_body,
        company_name=company_name,
    )


router = APIRouter(tags=["Authentication"])


@router.post("/companies/register", response_model=Token)
async def register_company(
    data: CompanyRegister,
    session: Session = Depends(get_session),
):
    slug = data.company_slug.strip().lower()
    email = data.admin_email.lower().strip()

    existing_company = session.exec(select(Company).where(Company.slug == slug)).first()
    if existing_company:
        raise HTTPException(status_code=400, detail="Company slug already exists")

    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    company = Company(
        name=data.company_name.strip(),
        slug=slug,
        status="active",
        subscription_tier="starter",
        max_users=10,
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    username_raw = data.username.strip()
    if not username_raw:
        raise HTTPException(status_code=400, detail="Username is required")
    username_normalized = username_raw.lower()
    existing_username = session.exec(
        select(User).where(User.username_normalized == username_normalized)
    ).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        company_id=company.id,
        email=email,
        username=username_raw,
        username_normalized=username_normalized,
        password_hash=get_password_hash(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        is_active=True,
        email_verified=False,
        phone=data.phone_number,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    create_default_permissions(session)
    roles = create_default_roles_for_company(session, company.id, user.id)
    seed_default_role_permissions(session, roles)

    session.add(UserRole(user_id=user.id, role_id=roles["company_owner"].id))
    session.commit()

    verification_token = _generate_verification_token(session, user)
    _send_verification_email(user, verification_token, company.name)

    token = create_access_token(
        {
            "user_id": user.id,
            "company_id": user.company_id,
            "token_version": user.token_version,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token)


class EmailVerificationRequest(SQLModel):
    token: str


class ResendVerificationRequest(SQLModel):
    email: str


class InviteInfo(SQLModel):
    email: str
    company_name: str
    company_website: str
    invited_by: str
    role_name: str
    expires_at: datetime


class MFAVerifyRequest(SQLModel):
    token: str


class MFADisableRequest(SQLModel):
    token: str


class RevealVerifyRequest(SQLModel):
    token: str


class UserUpdateRequest(SQLModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    company_website: Optional[str] = None


def _verify_email_token(session: Session, token_value: str) -> User:
    normalized_token = token_value.strip()
    user = session.exec(
        select(User).where(User.email_verification_token == normalized_token)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Invalid verification token")

    if not user.email_verification_expires_at or user.email_verification_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Verification token expired")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires_at = None
    session.add(user)
    session.commit()
    return user


@router.post("/verify-email")
async def verify_email(
    data: EmailVerificationRequest,
    session: Session = Depends(get_session),
):
    _verify_email_token(session, data.token)
    return {"status": "verified"}


@router.post("/auth/verify-email")
async def verify_email_alias(
    data: EmailVerificationRequest,
    session: Session = Depends(get_session),
):
    return await verify_email(data, session)


@router.get("/verify-email")
async def verify_email_get(
    token: str,
    session: Session = Depends(get_session),
):
    _verify_email_token(session, token)
    return {"status": "verified"}


@router.get("/auth/verify-email")
async def verify_email_get_alias(
    token: str,
    session: Session = Depends(get_session),
):
    return await verify_email_get(token, session)


@router.post("/verify-email/resend")
async def resend_verification(
    data: ResendVerificationRequest,
    session: Session = Depends(get_session),
):
    email = data.email.lower().strip()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.email_verified:
        return {"status": "already_verified"}

    token = _generate_verification_token(session, user)
    company = session.get(Company, user.company_id)
    _send_verification_email(user, token, company.name if company else "Rio CRM")
    return {"status": "sent"}


@router.post("/auth/verify-email/resend")
async def resend_verification_alias(
    data: ResendVerificationRequest,
    session: Session = Depends(get_session),
):
    return await resend_verification(data, session)


@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    identifier_input = form_data.username.strip()
    identifier_lower = identifier_input.lower()
    user = session.exec(
        select(User).where(
            or_(
                User.email == identifier_lower,
                User.username_normalized == identifier_lower,
            )
        )
    ).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        session.add(
            LoginHistory(
                company_id=user.company_id if user else None,
                user_id=user.id if user else None,
                email=user.email if user else identifier_lower,
                event_type="login_failure",
                success=False,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                failure_reason="incorrect_credentials",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        session.add(
            LoginHistory(
                company_id=user.company_id,
                user_id=user.id,
                email=user.email,
                event_type="login_failure",
                success=False,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                failure_reason="inactive_user",
            )
        )
        session.commit()
        raise HTTPException(status_code=403, detail="Inactive user")

    if not user.email_verified:
        session.add(
            LoginHistory(
                company_id=user.company_id,
                user_id=user.id,
                email=user.email,
                event_type="login_failure",
                success=False,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                failure_reason="email_not_verified",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=403,
            detail={
                "code": "EMAIL_UNVERIFIED",
                "message": "Email address not verified",
                "email": user.email,
            },
        )

    mfa_token = request.query_params.get("mfa_token")
    if user.mfa_enabled:
        if not mfa_token:
            session.add(
                LoginHistory(
                    company_id=user.company_id,
                    user_id=user.id,
                    email=user.email,
                    event_type="login_failure",
                    success=False,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    failure_reason="mfa_required",
                )
            )
            session.commit()
            raise HTTPException(status_code=403, detail="MFA_REQUIRED")

        if not user.mfa_secret or not verify_mfa_token(user.mfa_secret, mfa_token):
            session.add(
                LoginHistory(
                    company_id=user.company_id,
                    user_id=user.id,
                    email=user.email,
                    event_type="login_failure",
                    success=False,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    failure_reason="invalid_mfa",
                )
            )
            session.commit()
            raise HTTPException(status_code=401, detail="Invalid MFA token")

    user.last_login_at = utc_now()
    session.add(user)
    session.add(
        LoginHistory(
            company_id=user.company_id,
            user_id=user.id,
            email=user.email,
            event_type="login_success",
            success=True,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    session.commit()

    token = create_access_token(
        {
            "user_id": user.id,
            "company_id": user.company_id,
            "token_version": user.token_version,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token)


@router.post("/auth/mfa/setup")
async def setup_mfa(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")

    secret = generate_mfa_secret()
    current_user.mfa_secret = secret
    session.add(current_user)
    session.commit()

    uri = get_mfa_provisioning_uri(current_user.username or current_user.email, secret)
    qr_code = generate_mfa_qr_base64(uri)

    return {"secret": secret, "qr_code": qr_code}


@router.post("/auth/mfa/enable")
async def enable_mfa(
    data: MFAVerifyRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    if not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up")

    if not verify_mfa_token(current_user.mfa_secret, data.token):
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    current_user.mfa_enabled = True
    session.add(current_user)
    session.commit()

    company_name, company_website = _get_company_info(session, current_user)
    subject = "Rio CRM: Two-Factor Authentication Enabled"
    email_body = (
        f"Hello {current_user.username or current_user.email},\n\n"
        "Two-Factor Authentication (2FA) has been successfully enabled on your account. "
        "You will now be required to enter a code from your authenticator app whenever you log in."
    )
    styled_html = get_styled_html(
        "MFA Enabled Successfully",
        "Your account is now protected with 2FA.<br><br>You will be required to enter a code from your authenticator app every time you log in.",
        lead_name=current_user.first_name or current_user.username or "valued customer",
        company_name=company_name,
        company_website=company_website,
    )
    send_smtp_email(
        to_email=current_user.email,
        subject=subject,
        body=email_body,
        html_body=styled_html,
        company_name=company_name,
    )

    return {"message": "MFA enabled successfully"}


@router.post("/auth/mfa/request-disable")
async def request_mfa_disable(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    otp = "".join(str(random.randint(0, 9)) for _ in range(6))
    current_user.mfa_disable_otp = otp
    session.add(current_user)
    session.commit()

    company_name, company_website = _get_company_info(session, current_user)
    subject = "Rio CRM: OTP to disable Two-Factor Authentication"
    email_body = (
        f"Hello {current_user.username or current_user.email},\n\n"
        f"Your OTP to disable Two-Factor Authentication is: {otp}\n\n"
        "If you did not request this change, please contact support immediately."
    )
    styled_html = get_styled_html(
        "MFA Disable OTP",
        f"You have requested to disable 2FA on your account. Your verification code is:<br><br>"
        f"<span style='font-size: 24px; font-weight: bold; color: #7c3aed; letter-spacing: 5px;'>{otp}</span>"
        "<br><br>If you did not request this, please ignore this email.",
        lead_name=current_user.first_name or current_user.username or "valued customer",
        company_name=company_name,
        company_website=company_website,
    )
    send_smtp_email(
        to_email=current_user.email,
        subject=subject,
        body=email_body,
        html_body=styled_html,
        company_name=company_name,
    )

    return {"message": "OTP sent to your registered email"}


@router.post("/auth/mfa/disable")
async def disable_mfa(
    request: MFADisableRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    if not current_user.mfa_disable_otp or request.token != current_user.mfa_disable_otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_disable_otp = None
    session.add(current_user)
    session.commit()

    company_name, company_website = _get_company_info(session, current_user)
    subject = "Rio CRM: Two-Factor Authentication Disabled"
    email_body = (
        f"Hello {current_user.username or current_user.email},\n\n"
        "Two-Factor Authentication (2FA) has been disabled on your account as requested."
    )
    styled_html = get_styled_html(
        "MFA Disabled Successfully",
        "Two-Factor Authentication has been removed from your account.<br><br>If you did not request this, please secure your account immediately.",
        lead_name=current_user.first_name or current_user.username or "valued customer",
        company_name=company_name,
        company_website=company_website,
    )
    send_smtp_email(
        to_email=current_user.email,
        subject=subject,
        body=email_body,
        html_body=styled_html,
        company_name=company_name,
    )

    return {"message": "MFA disabled successfully"}


@router.post("/auth/reveal/request")
async def request_reveal_code(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    code = f"{random.randint(0, 999999):06d}"
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    current_user.reveal_code = code
    current_user.reveal_code_expires_at = expiry
    session.add(current_user)
    session.commit()

    company_name, company_website = _get_company_info(session, current_user)
    _send_reveal_code_email(current_user, company_name, company_website, code)

    return {"message": "Verification code sent"}


@router.post("/auth/reveal/verify")
async def verify_reveal_code(
    data: RevealVerifyRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.reveal_code or not current_user.reveal_code_expires_at:
        raise HTTPException(status_code=400, detail="No reveal request in progress")
    if current_user.reveal_code_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Code expired")
    if data.token.strip() != current_user.reveal_code:
        raise HTTPException(status_code=400, detail="Invalid code")

    current_user.reveal_code = None
    current_user.reveal_code_expires_at = None
    session.add(current_user)
    session.commit()

    return {"status": "revealed"}


@router.delete("/auth/me")
async def delete_my_account(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    company_name, company_website = _get_company_info(session, current_user)
    user_role = _get_user_role(session, current_user.id)
    current_user.is_active = False
    session.add(current_user)
    session.commit()

    subject = "Your Rio CRM Account has been Deleted"
    email_body = (
        f"Hello {current_user.username or current_user.email},\n\n"
        f"Your account (Role: {user_role}) has been deleted from Rio CRM as requested.\n\n"
        "If this was a mistake, please reach out to support."
    )
    styled_html = get_styled_html(
        subject,
        f"Your account with the role <strong>{user_role}</strong> has been removed from our system.<br><br>We're sorry to see you go!",
        lead_name=current_user.first_name or current_user.username or "valued customer",
        company_name=company_name,
        company_website=company_website,
    )
    send_smtp_email(
        to_email=current_user.email,
        subject=subject,
        body=email_body,
        html_body=styled_html,
        company_name=company_name,
    )

    return {"status": "deleted"}


@router.post("/logout-all")
async def logout_all(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    current_user.token_version += 1
    session.add(current_user)
    session.commit()
    return {"status": "logged_out_everywhere"}


@router.post("/auth/logout-all")
async def logout_all_alias(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await logout_all(session=session, current_user=current_user)


@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    extension = Path(file.filename).suffix or ""
    target_name = f"{uuid4().hex}{extension}"
    target_path = UPLOADS_DIR / target_name
    contents = await file.read()
    target_path.write_bytes(contents)
    current_user.profile_picture_url = f"/uploads/{target_name}"
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return {"url": current_user.profile_picture_url}


@router.post("/auth/upload-avatar")
async def upload_avatar_alias(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await upload_avatar(file=file, session=session, current_user=current_user)


@router.post("/company-profile/logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    extension = Path(file.filename).suffix or ""
    target_name = f"{uuid4().hex}{extension}"
    target_path = UPLOADS_DIR / target_name
    contents = await file.read()
    target_path.write_bytes(contents)

    company = session.get(Company, current_user.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company.logo_url = f"/uploads/{target_name}"
    session.add(company)
    session.commit()
    session.refresh(company)
    return {"logo_url": company.logo_url}


@router.get("/login-history")
async def get_login_history(
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    query = select(LoginHistory).where(
        LoginHistory.company_id == current_user.company_id,
        LoginHistory.user_id == current_user.id,
    )
    logs = session.exec(
        query.order_by(LoginHistory.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return logs


@router.get("/auth/login-history")
async def get_login_history_alias(
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await get_login_history(limit=limit, offset=offset, session=session, current_user=current_user)


def _build_google_status(session: Session, company_id: int) -> dict:
    refresh_token = _get_company_setting_value(session, company_id, "GOOGLE_REFRESH_TOKEN")
    access_token = _get_company_setting_value(session, company_id, "GOOGLE_ACCESS_TOKEN")
    expiry = _get_company_setting_value(session, company_id, "GOOGLE_TOKEN_EXPIRY")
    email = _get_company_setting_value(session, company_id, "GOOGLE_USER_EMAIL")
    status = "connected" if refresh_token else "disconnected"
    message = "Google linked" if refresh_token else "Google integration is not configured"
    return {"status": status, "email": email, "expiry": expiry, "message": message, "access_token": access_token}


@router.get("/google/status")
async def google_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return _build_google_status(session, current_user.company_id)


@router.get("/google/url")
async def google_auth_url(
    current_user: User = Depends(get_current_user),
):
    flow = _get_google_flow()
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes=True, prompt="consent")
    GOOGLE_STATE_CACHE[current_user.id] = state
    return {"auth_url": auth_url, "state": state}


@router.post("/google/callback")
async def google_callback(
    data: GoogleAuthRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not data.code:
        raise HTTPException(status_code=400, detail="code is required")
    expected_state = GOOGLE_STATE_CACHE.get(current_user.id)
    if expected_state and data.state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid state token")
    flow = _get_google_flow()
    try:
        flow.fetch_token(code=data.code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Token exchange failed") from exc
    creds = flow.credentials
    refresh_token = creds.refresh_token or _get_company_setting_value(session, current_user.company_id, "GOOGLE_REFRESH_TOKEN")
    _upsert_company_setting(session, current_user.company_id, "GOOGLE_REFRESH_TOKEN", refresh_token, current_user.id, True)
    _upsert_company_setting(session, current_user.company_id, "GOOGLE_ACCESS_TOKEN", creds.token, current_user.id, True)
    expiry = creds.expiry.isoformat() if creds.expiry else None
    _upsert_company_setting(session, current_user.company_id, "GOOGLE_TOKEN_EXPIRY", expiry, current_user.id)
    _upsert_company_setting(session, current_user.company_id, "GOOGLE_TOKEN_SCOPE", " ".join(creds.scopes or []), current_user.id)
    user_email = None
    try:
        headers = {"Authorization": f"Bearer {creds.token}"}
        response = requests.get("https://www.googleapis.com/oauth2/v1/userinfo?alt=json", headers=headers, timeout=10)
        if response.ok:
            payload = response.json()
            user_email = payload.get("email")
    except Exception:
        logger.warning("Unable to fetch Google profile for user %s", current_user.id)
    if user_email:
        _upsert_company_setting(session, current_user.company_id, "GOOGLE_USER_EMAIL", user_email, current_user.id)
    GOOGLE_STATE_CACHE.pop(current_user.id, None)
    return {"status": "connected", "email": user_email}


@router.delete("/google/disconnect")
async def google_disconnect(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    keys = [
        "GOOGLE_REFRESH_TOKEN",
        "GOOGLE_ACCESS_TOKEN",
        "GOOGLE_TOKEN_EXPIRY",
        "GOOGLE_TOKEN_SCOPE",
        "GOOGLE_USER_EMAIL",
    ]
    for key in keys:
        _delete_company_setting(session, current_user.company_id, key)
    return {"status": "disconnected"}


@router.get("/auth/google/status")
async def google_status_alias(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return await google_status(current_user=current_user, session=session)


@router.get("/auth/google/url")
async def google_url_alias(
    current_user: User = Depends(get_current_user),
):
    return await google_auth_url(current_user=current_user)


@router.post("/auth/google/callback")
async def google_callback_alias(
    current_user: User = Depends(get_current_user),
):
    return await google_callback(current_user=current_user)


@router.delete("/auth/google/disconnect")
async def google_disconnect_alias(
    current_user: User = Depends(get_current_user),
):
    return await google_disconnect(current_user=current_user)


@router.post("/invites")
async def create_invite(
    data: InviteCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.invite")),
):
    invite_email = data.email.lower().strip()

    existing_user = session.exec(select(User).where(User.email == invite_email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    role = session.exec(
        select(Role).where(
            Role.id == data.role_id,
            Role.company_id == current_user.company_id,
        )
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    invite = Invite(
        company_id=current_user.company_id,
        email=invite_email,
        role_id=role.id,
        token=secrets.token_urlsafe(32),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=data.expires_in_hours),
        invited_by=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)

    company = session.get(Company, current_user.company_id)
    _send_invite_email(session, company, invite)

    return {
        "id": invite.id,
        "email": invite.email,
        "token": invite.token,
        "expires_at": invite.expires_at,
    }


@router.post("/auth/invites")
async def create_invite_alias(
    data: InviteCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.invite")),
):
    return await create_invite(data, session, current_user)


@router.get("/auth/invites/accept", response_model=InviteInfo)
async def get_invite_info(
    token: str,
    session: Session = Depends(get_session),
):
    invite = session.exec(select(Invite).where(Invite.token == token)).first()
    if not invite or invite.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite expired")

    company = session.get(Company, invite.company_id)
    company_name = company.name if company else "Rio CRM"
    company_website = company.website or f"https://{company.domain or company.slug or 'rio-crm.example.com'}" if company else "https://rio-crm.example.com/"
    inviter = session.get(User, invite.invited_by)
    inviter_name = (
        f"{inviter.first_name or ''} {inviter.last_name or ''}".strip()
        or inviter.username
        or inviter.email
        if inviter
        else "Your teammate"
    )
    role = session.get(Role, invite.role_id)
    role_name = role.name.replace("_", " ") if role else "teammate"

    return InviteInfo(
        email=invite.email,
        company_name=company_name,
        company_website=company_website,
        invited_by=inviter_name,
        role_name=role_name,
        expires_at=invite.expires_at,
    )


@router.post("/invites/accept", response_model=Token)
async def accept_invite(
    data: InviteAccept,
    session: Session = Depends(get_session),
):
    email = data.email.lower().strip()
    invite = session.exec(select(Invite).where(Invite.token == data.token)).first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Invite is not active")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite expired")
    if invite.email.lower().strip() != email:
        raise HTTPException(status_code=400, detail="Invite email mismatch")

    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    desired_username = (data.username or email).strip()
    normalized_username = desired_username.lower()
    username_conflict = session.exec(
        select(User).where(User.username_normalized == normalized_username)
    ).first()
    if username_conflict:
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        company_id=invite.company_id,
        email=email,
        username=desired_username,
        username_normalized=normalized_username,
        password_hash=get_password_hash(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        is_active=True,
        email_verified=True,
        created_by=invite.invited_by,
        updated_by=invite.invited_by,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    session.add(UserRole(user_id=user.id, role_id=invite.role_id))
    invite.status = "accepted"
    invite.accepted_by = user.id
    invite.accepted_at = datetime.now(timezone.utc)
    invite.updated_by = user.id
    session.add(invite)
    session.commit()

    token = create_access_token(
        {
            "user_id": user.id,
            "company_id": user.company_id,
            "token_version": user.token_version,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token)


@router.post("/auth/invites/accept", response_model=Token)
async def accept_invite_alias(
    data: InviteAccept,
    session: Session = Depends(get_session),
):
    return await accept_invite(data, session)


@router.get("/users/me")
async def get_me(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _serialize_user(session, current_user)


@router.patch("/users/me")
async def update_me(
    data: UserUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    has_user_changes = False

    if data.first_name is not None:
        current_user.first_name = data.first_name.strip()
        has_user_changes = True
    if data.last_name is not None:
        current_user.last_name = data.last_name.strip()
        has_user_changes = True
    if data.phone_number is not None:
        current_user.phone = data.phone_number.strip()
        has_user_changes = True
    if has_user_changes:
        session.add(current_user)

    if data.company_name is not None or data.company_website is not None:
        company = session.get(Company, current_user.company_id)
        if company:
            if data.company_name is not None:
                company.name = data.company_name.strip()
            if data.company_website is not None:
                company.website = data.company_website.strip()
            session.add(company)

    if has_user_changes or data.company_name is not None or data.company_website is not None:
        session.commit()
        session.refresh(current_user)


@router.get("/company-profile", response_model=CompanyProfileResponse)
async def get_company_profile(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    company = session.get(Company, current_user.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return _serialize_company(company)


@router.patch("/company-profile", response_model=CompanyProfileResponse)
async def update_company_profile(
    data: CompanyProfileUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    company = session.get(Company, current_user.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if data.name is not None:
        company.name = data.name.strip()
    if data.website is not None:
        company.website = data.website.strip()
    if data.domain is not None:
        company.domain = data.domain.strip()
    if data.logo_url is not None:
        company.logo_url = data.logo_url.strip()
    if data.primary_color is not None:
        company.primary_color = data.primary_color.strip()
    if data.status is not None:
        company.status = data.status.strip()
    if data.subscription_tier is not None:
        company.subscription_tier = data.subscription_tier.strip()
    if data.max_users is not None:
        company.max_users = data.max_users
    if data.slug is not None:
        slug = data.slug.strip().lower()
        if slug:
            existing = session.exec(
                select(Company).where(Company.slug == slug, Company.id != company.id)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Slug already in use")
            company.slug = slug

    try:
        session.add(company)
        session.commit()
        session.refresh(company)
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Failed to update company profile")

    return _serialize_company(company)

    return _serialize_user(session, current_user)
