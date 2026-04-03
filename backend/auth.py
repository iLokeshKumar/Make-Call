import base64
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import bcrypt
import jwt
import pyotp
import qrcode
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from database import get_session
from models.models import User
from services.auth_service import get_user_permission_keys

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


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


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

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
