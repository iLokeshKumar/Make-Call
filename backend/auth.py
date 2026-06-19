import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import bcrypt
import httpx
import jwt
import pyotp
import qrcode
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from csrf import (
    CSRF_BYPASS_PREFIXES,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    generate_csrf_token,
    verify_csrf_invariants,
)
from database import get_session
from models.models import User
from services.core.auth_service import get_user_permission_keys


__all__ = [
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "ALGORITHM",
    "CSRF_BYPASS_PREFIXES",
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "PermissionChecker",
    "SECRET_KEY",
    "SESSION_COOKIE_NAME",
    "clear_auth_cookie",
    "clear_csrf_cookie",
    "create_access_token",
    "generate_csrf_token",
    "generate_mfa_qr_base64",
    "generate_mfa_secret",
    "get_current_active_user",
    "get_current_user",
    "get_mfa_provisioning_uri",
    "get_password_hash",
    "oauth2_scheme",
    "set_auth_cookie",
    "set_csrf_cookie",
    "check_pwned_password",
    "validate_password_rules",
    "verify_csrf_invariants",
    "verify_mfa_token",
    "verify_password",
]

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# OAuth2 scheme stays for OpenAPI docs + bearer-token clients (mobile, scripts). `auto_error=False` makes the header optional so we can fall back to a cookie.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)


def set_auth_cookie(response: Response, token: str) -> None:
    """Store the session JWT as an httpOnly cookie.

    httpOnly blocks JavaScript access (XSS can't exfiltrate the token).
    Secure restricts to HTTPS in production (set COOKIE_SECURE=0 for local dev).
    SameSite=Lax blocks classic CSRF on cross-site form posts while still
    allowing top-level navigation to carry the cookie.
    """
    secure = os.getenv("COOKIE_SECURE", "1") == "1"
    samesite = os.getenv("COOKIE_SAMESITE", "lax").lower()
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"
    domain = os.getenv("COOKIE_DOMAIN") or None
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the session cookie. Used on /auth/logout."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        domain=os.getenv("COOKIE_DOMAIN") or None,
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set the CSRF double-submit cookie alongside the session cookie.

    Non-httpOnly on purpose — the SPA reads this cookie with JavaScript and
    echoes the value back in the `X-CSRF-Token` header. The session cookie
    stays httpOnly; only the CSRF token is JS-readable. That pairing is what
    makes the pattern XSS-resistant (attacker can read the CSRF cookie but
    not the session cookie that carries auth).
    """
    secure = os.getenv("COOKIE_SECURE", "1") == "1"
    samesite = os.getenv("COOKIE_SAMESITE", "lax").lower()
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"
    domain = os.getenv("COOKIE_DOMAIN") or None
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=False, # intentional — SPA must read this
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    """Remove the CSRF cookie. Call alongside clear_auth_cookie on logout."""
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        domain=os.getenv("COOKIE_DOMAIN") or None,
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def validate_password_rules(
    password: str,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone_number: str | None = None,
) -> Optional[str]:
    if len(password) < 6:
        return "Password must be at least 6 characters long"

    has_lower = any(char.islower() for char in password)
    has_upper = any(char.isupper() for char in password)
    has_digit = any(char.isdigit() for char in password)
    has_special = any(char in "!@#$%^&*()_+-=[]{}|;:'\",.<>/?`~" for char in password)

    if not (has_lower and has_upper and has_digit and has_special):
        return "Password must contain lowercase, uppercase, number, and special character"

    lowered = password.lower()
    for value, label in (
        (username, "username"),
        (first_name, "first name"),
        (last_name, "last name"),
    ):
        if value and value.lower() in lowered:
            return f"Password cannot contain the {label}"

    if phone_number and phone_number in password:
        return "Password cannot contain the phone number"

    return None


async def check_pwned_password(password: str) -> bool:
    """True if password appears in HIBP breach database. Uses k-anonymity — only SHA-1 prefix sent."""
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={"Add-Padding": "true"},
            )
        for line in resp.text.splitlines():
            h, _ = line.split(":")
            if h == suffix:
                return True
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    request: Request,
    header_token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Resolve the authenticated user from a session cookie or bearer header.

    The cookie takes precedence so frontends can migrate fetch-by-fetch
    without a flag day. Both paths decode the same JWT.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = request.cookies.get(SESSION_COOKIE_NAME) or header_token
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        company_id = payload.get("company_id")
        token_version = payload.get("token_version")
        if not user_id or not company_id:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_exception

    if user.company_id != company_id or user.token_version != token_version:
        raise credentials_exception

    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


class PermissionChecker:
    def __init__(self, permission_key: str):
        self.permission_key = permission_key

    def __call__(
        self,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session),
    ) -> User:
        permissions = get_user_permission_keys(session, current_user.id)
        if self.permission_key not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return current_user


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def verify_mfa_token(secret: str, token: str) -> bool:
    return pyotp.TOTP(secret).verify(token)


def get_mfa_provisioning_uri(username: str, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name="Rio CRM")


def generate_mfa_qr_base64(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
