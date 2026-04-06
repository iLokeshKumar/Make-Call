import os
from typing import Optional

from sqlmodel import Session, select

from models.models import CompanySetting, UserSetting
from utils.encryption import decrypt_value, encrypt_value

# Keys stored encrypted in UserSetting
_USER_SECRET_KEYS = {
    "SMTP_PASSWORD", "IMAP_PASSWORD", "SMTP_USERNAME", "IMAP_USERNAME",
}


def get_user_setting_value(
    session: Session,
    user_id: int,
    key: str,
) -> Optional[str]:
    item = session.exec(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == key,
        )
    ).first()
    if not item:
        return None
    return decrypt_value(item.value) if key in _USER_SECRET_KEYS else item.value


def save_user_setting(
    session: Session,
    user_id: int,
    key: str,
    value: str,
) -> None:
    """Upsert a UserSetting row (encrypts secret keys). Does NOT commit."""
    from models.models import utc_now
    stored = encrypt_value(value) if key in _USER_SECRET_KEYS else value
    row = session.exec(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == key,
        )
    ).first()
    if row:
        row.value = stored
        row.updated_at = utc_now()
    else:
        row = UserSetting(user_id=user_id, key=key, value=stored)
    session.add(row)


def get_email_credential(
    session: Session,
    company_id: int,
    actor_user_id: int,
    key: str,
) -> Optional[str]:
    """Return email credential — user-level first, company-level fallback."""
    val = get_user_setting_value(session, actor_user_id, key)
    return val or get_company_credential(session, company_id, key)


def get_company_setting_value(
    session: Session,
    company_id: int,
    key: str,
) -> Optional[str]:
    item = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not item:
        return None
    return decrypt_value(item.value) if item.is_secret else item.value


def get_company_credential(
    session: Session,
    company_id: int,
    key: str,
    env_fallback: bool = True,
) -> Optional[str]:
    value = get_company_setting_value(session, company_id, key)
    if value:
        return value
    return os.getenv(key) if env_fallback else None


def get_credential(
    session: Session,
    company_id: int,
    key: str,
    default: Optional[str] = None,
    env_fallback: bool = True,
) -> Optional[str]:
    """Helper that mirrors the older get_credential signature."""
    value = get_company_setting_value(session, company_id, key)
    if value:
        return value
    if env_fallback:
        return os.getenv(key, default)
    return default
