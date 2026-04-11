"""
IMAP Poller — pulls inbound emails for every company that has IMAP configured.
Uses Python stdlib imaplib only (no extra dependency).

Flow per poll cycle:
  1. Find all companies with IMAP_SERVER set in CompanySettings.
  2. For each company: connect via IMAP4_SSL, fetch emails with UID > last known UID.
  3. Parse each email (From / To / Subject / Body).
  4. Call ingest_email_webhook_event() — same function the Mailgun/SendGrid webhook uses.
  5. Save the highest processed UID back to CompanySettings so we never re-process.

IMAP credentials resolved in priority order:
  IMAP_SERVER  → SMTP_HOST  (fallback to same server)
  IMAP_PORT    → 993
  IMAP_USERNAME→ SMTP_USERNAME
  IMAP_PASSWORD→ SMTP_PASSWORD

Run from main.py lifespan as asyncio.create_task(imap_poll_loop()).
"""

import asyncio
import email as _email_lib
import imaplib
import logging
from email.header import decode_header as _decode_header

from sqlmodel import Session, select

from database import engine
from models.models import CompanySetting

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 180  # poll every 3 minutes


# Header / body helpers

def _decode(value: str | bytes | None, charset: str | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(charset or "utf-8", errors="replace")
    return value


def _parse_header(raw: str | None) -> str:
    """Decode a potentially RFC-2047-encoded header value."""
    if not raw:
        return ""
    parts = []
    for fragment, charset in _decode_header(raw):
        parts.append(_decode(fragment, charset))
    return " ".join(parts).strip()


def _safe_decode(payload: bytes, charset: str) -> str:
    """Decode bytes to str, falling back through common charsets on failure."""
    # Normalize charset — "binary", "unknown-8bit", etc. are not real codecs
    _FALLBACK_CHARSETS = ("utf-8", "latin-1", "cp1252")
    normalized = (charset or "utf-8").strip().lower()
    if normalized in ("binary", "unknown", "unknown-8bit", "x-unknown", ""):
        normalized = "utf-8"
    try:
        return payload.decode(normalized, errors="replace")
    except (LookupError, UnicodeDecodeError):
        for cs in _FALLBACK_CHARSETS:
            try:
                return payload.decode(cs, errors="replace")
            except (LookupError, UnicodeDecodeError):
                continue
    return payload.decode("latin-1", errors="replace")


def _extract_body(msg) -> tuple[str, str]:
    """Return (plain_text, html_text) from an email.message object."""
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = _safe_decode(payload, charset)
            if ct == "text/plain" and not plain:
                plain = text
            elif ct == "text/html" and not html:
                html = text
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            text = _safe_decode(payload, charset)
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text
    return plain, html


# Per-company last-UID tracking (stored in CompanySettings)

_LAST_UID_KEY = "IMAP_LAST_UID"


def _get_last_uid(session: Session, company_id: int) -> int:
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == _LAST_UID_KEY,
        )
    ).first()
    try:
        return int(row.value) if row and row.value else 0
    except (ValueError, TypeError):
        return 0


def _save_last_uid(session: Session, company_id: int, uid: int) -> None:
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == _LAST_UID_KEY,
        )
    ).first()
    if row:
        row.value = str(uid)
    else:
        row = CompanySetting(
            company_id=company_id,
            key=_LAST_UID_KEY,
            value=str(uid),
            is_secret=False,
        )
    session.add(row)
    session.commit()


# Credential resolution

def _cred(session: Session, company_id: int, *keys: str) -> str:
    """Return the first non-empty credential from the given keys."""
    from credentials_service import get_company_credential
    for key in keys:
        val = get_company_credential(session, company_id, key)
        if val:
            return val
    return ""


def _get_imap_config(session: Session, company_id: int) -> dict | None:
    host = _cred(session, company_id, "IMAP_SERVER", "SMTP_HOST")
    port = int(_cred(session, company_id, "IMAP_PORT") or 993)
    user = _cred(session, company_id, "IMAP_USERNAME", "SMTP_USERNAME")
    password = _cred(session, company_id, "IMAP_PASSWORD", "SMTP_PASSWORD")
    security = (_cred(session, company_id, "IMAP_SECURITY") or "").strip().lower()
    if security not in ("ssl", "starttls", "none"):
        security = "ssl" if port == 993 else "starttls"
    if not host or not user or not password:
        return None
    return {"host": host, "port": port, "user": user, "password": password, "security": security}


# Core per-company poll (synchronous — called in executor)

def poll_company_inbox(company_id: int) -> int:
    """
    Fetch new emails for one company via IMAP and ingest them.
    Returns number of emails processed (not skipped).
    """
    from services.inbound_email_service import ingest_email_webhook_event

    with Session(engine) as session:
        cfg = _get_imap_config(session, company_id)
        if not cfg:
            return 0
        last_uid = _get_last_uid(session, company_id)

    processed = 0
    new_max_uid = last_uid

    try:
        if cfg["security"] == "ssl":
            mail = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        else:
            mail = imaplib.IMAP4(cfg["host"], cfg["port"])
            if cfg["security"] == "starttls":
                mail.starttls()
        mail.login(cfg["user"], cfg["password"])
        mail.select("INBOX", readonly=True)   # readonly — don't mark as read

        # Fetch UIDs greater than last processed
        if last_uid == 0:
            status, data = mail.uid("search", None, "ALL")
        else:
            status, data = mail.uid("search", None, f"UID {last_uid + 1}:*")

        if status != "OK" or not data or not data[0]:
            mail.logout()
            return 0

        uid_list = [u for u in data[0].split() if int(u) > last_uid]
        if not uid_list:
            mail.logout()
            return 0

        # Cap at 50 per cycle to avoid blocking for too long
        for uid_bytes in uid_list[:50]:
            uid = int(uid_bytes)
            fetch_status, msg_data = mail.uid("fetch", uid_bytes, "(RFC822)")
            if fetch_status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = _email_lib.message_from_bytes(raw)

            from_raw = msg.get("From", "")
            to_raw   = msg.get("To", "")
            subject  = _parse_header(msg.get("Subject"))
            msg_id   = (msg.get("Message-ID") or "").strip()
            in_reply  = (msg.get("In-Reply-To") or "").strip()
            plain, html = _extract_body(msg)
            body = plain or html

            # Build a normalised payload — same shape ingest_email_webhook_event expects
            payload = {
                "From":       _parse_header(from_raw),
                "To":         _parse_header(to_raw),
                "Subject":    subject,
                "Message-ID": msg_id,
                "In-Reply-To": in_reply,
                "Body":       body,
                "TextBody":   plain,
                "HtmlBody":   html,
            }

            with Session(engine) as session:
                result = ingest_email_webhook_event(
                    session, payload, forced_company_id=company_id
                )
            status_str = result.get("status", "?")
            reason = result.get("reason", "")
            logger.debug(
                "[IMAP] company=%s uid=%s → %s %s",
                company_id, uid, status_str, reason,
            )
            if status_str not in ("ignored",):
                processed += 1

            if uid > new_max_uid:
                new_max_uid = uid

        mail.logout()

    except imaplib.IMAP4.error as exc:
        logger.error("[IMAP] company=%s IMAP error: %s", company_id, exc)
    except OSError as exc:
        logger.error("[IMAP] company=%s connection error: %s", company_id, exc)
    except Exception as exc:
        logger.exception("[IMAP] company=%s unexpected error: %s", company_id, exc)

    # Persist watermark even if some messages were skipped (duplicates etc.)
    if new_max_uid > last_uid:
        with Session(engine) as session:
            _save_last_uid(session, company_id, new_max_uid)

    return processed


# Company discovery

def get_companies_with_imap() -> list[int]:
    """Return company IDs that have IMAP_SERVER (or SMTP_HOST) configured."""
    with Session(engine) as session:
        rows = session.exec(
            select(CompanySetting.company_id).where(
                CompanySetting.key.in_(["IMAP_SERVER", "SMTP_HOST"]),
                CompanySetting.value.isnot(None),
                CompanySetting.value != "",
            )
        ).all()
    return list(set(rows))


# Per-user inbox polling

def _get_user_imap_config(session: Session, user_id: int) -> dict | None:
    from credentials_service import get_user_setting_value
    host = get_user_setting_value(session, user_id, "IMAP_SERVER")
    if not host:
        return None
    port = int(get_user_setting_value(session, user_id, "IMAP_PORT") or 993)
    user = get_user_setting_value(session, user_id, "IMAP_USERNAME")
    password = get_user_setting_value(session, user_id, "IMAP_PASSWORD")
    if not user or not password:
        return None
    security = (get_user_setting_value(session, user_id, "IMAP_SECURITY") or "").strip().lower()
    if security not in ("ssl", "starttls", "none"):
        security = "ssl" if port == 993 else "starttls"
    return {"host": host, "port": port, "user": user, "password": password, "security": security}


def get_users_with_imap() -> list[tuple[int, int]]:
    """Return (user_id, company_id) pairs for users with personal IMAP_SERVER configured."""
    from models.models import UserSetting, User
    with Session(engine) as session:
        rows = session.exec(
            select(UserSetting.user_id).where(
                UserSetting.key == "IMAP_SERVER",
                UserSetting.value.isnot(None),
                UserSetting.value != "",
            )
        ).all()
        result = []
        for uid in set(rows):
            user_obj = session.get(User, uid)
            if user_obj and user_obj.is_active:
                result.append((uid, user_obj.company_id))
    return result


_USER_LAST_UID_KEY = "IMAP_LAST_UID"


def _get_user_last_uid(session: Session, user_id: int) -> int:
    from models.models import UserSetting
    row = session.exec(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == _USER_LAST_UID_KEY,
        )
    ).first()
    try:
        return int(row.value) if row and row.value else 0
    except (ValueError, TypeError):
        return 0


def _save_user_last_uid(session: Session, user_id: int, uid: int) -> None:
    from models.models import UserSetting, utc_now
    row = session.exec(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == _USER_LAST_UID_KEY,
        )
    ).first()
    if row:
        row.value = str(uid)
        row.updated_at = utc_now()
    else:
        row = UserSetting(user_id=user_id, key=_USER_LAST_UID_KEY, value=str(uid))
    session.add(row)
    session.commit()


def poll_user_inbox(user_id: int, company_id: int) -> int:
    """Fetch new emails from a user's personal IMAP inbox."""
    from services.inbound_email_service import ingest_email_webhook_event

    with Session(engine) as session:
        cfg = _get_user_imap_config(session, user_id)
        if not cfg:
            return 0
        last_uid = _get_user_last_uid(session, user_id)

    processed = 0
    new_max_uid = last_uid

    try:
        if cfg.get("security") == "ssl":
            mail = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        else:
            mail = imaplib.IMAP4(cfg["host"], cfg["port"])
            if cfg.get("security") == "starttls":
                mail.starttls()
        mail.login(cfg["user"], cfg["password"])
        mail.select("INBOX", readonly=True)

        if last_uid == 0:
            status, data = mail.uid("search", None, "ALL")
        else:
            status, data = mail.uid("search", None, f"UID {last_uid + 1}:*")

        if status != "OK" or not data or not data[0]:
            mail.logout()
            return 0

        uid_list = [u for u in data[0].split() if int(u) > last_uid]
        if not uid_list:
            mail.logout()
            return 0

        for uid_bytes in uid_list[:50]:
            uid = int(uid_bytes)
            fetch_status, msg_data = mail.uid("fetch", uid_bytes, "(RFC822)")
            if fetch_status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = _email_lib.message_from_bytes(raw)
            from_raw = msg.get("From", "")
            to_raw   = msg.get("To", "")
            subject  = _parse_header(msg.get("Subject"))
            msg_id   = (msg.get("Message-ID") or "").strip()
            in_reply  = (msg.get("In-Reply-To") or "").strip()
            plain, html = _extract_body(msg)

            payload = {
                "From":       _parse_header(from_raw),
                "To":         _parse_header(to_raw),
                "Subject":    subject,
                "Message-ID": msg_id,
                "In-Reply-To": in_reply,
                "Body":       plain or html,
                "TextBody":   plain,
                "HtmlBody":   html,
            }

            with Session(engine) as session:
                result = ingest_email_webhook_event(
                    session, payload, forced_company_id=company_id
                )
            status_str = result.get("status", "?")
            logger.debug(
                "[IMAP] user=%s uid=%s → %s",
                user_id, uid, status_str,
            )
            if status_str not in ("ignored",):
                processed += 1
            if uid > new_max_uid:
                new_max_uid = uid

        mail.logout()

    except imaplib.IMAP4.error as exc:
        msg = str(exc) or "(no detail — check IMAP is enabled in Gmail settings)"
        logger.error("[IMAP] user=%s IMAP protocol error: %s", user_id, msg)
    except OSError as exc:
        logger.error("[IMAP] user=%s connection error: %s", user_id, exc)
    except Exception as exc:
        logger.exception("[IMAP] user=%s unexpected error: %s", user_id, exc)

    if new_max_uid > last_uid:
        with Session(engine) as session:
            _save_user_last_uid(session, user_id, new_max_uid)

    return processed


# Async background loop — started from main.py lifespan

async def imap_poll_loop() -> None:
    """
    Runs forever as an asyncio background task.
    Polls all configured companies AND users every POLL_INTERVAL_SECONDS.
    IMAP calls are offloaded to a thread executor so they don't block the event loop.
    """
    logger.info("[IMAP] Poller started — interval %ds", POLL_INTERVAL_SECONDS)
    loop = asyncio.get_event_loop()

    while True:
        try:
            # Company-level inboxes
            company_ids = await loop.run_in_executor(None, get_companies_with_imap)
            for cid in company_ids:
                try:
                    count = await loop.run_in_executor(None, poll_company_inbox, cid)
                    if count:
                        logger.info("[IMAP] company=%s — %d new email(s) ingested", cid, count)
                except Exception as exc:
                    logger.error("[IMAP] company=%s poll failed: %s", cid, exc)

            # Per-user inboxes (personal IMAP credentials override company inbox)
            user_pairs = await loop.run_in_executor(None, get_users_with_imap)
            for uid, cid in user_pairs:
                try:
                    count = await loop.run_in_executor(None, poll_user_inbox, uid, cid)
                    if count:
                        logger.info("[IMAP] user=%s — %d new email(s) ingested", uid, count)
                except Exception as exc:
                    logger.error("[IMAP] user=%s poll failed: %s", uid, exc)

        except Exception as exc:
            logger.error("[IMAP] loop error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# Manual trigger endpoint helper

async def trigger_imap_poll(company_id: int, user_id: int | None = None) -> dict:
    """Trigger an immediate poll for a company (and optionally a specific user's inbox)."""
    loop = asyncio.get_event_loop()
    company_count = await loop.run_in_executor(None, poll_company_inbox, company_id)
    user_count = 0
    if user_id:
        user_count = await loop.run_in_executor(None, poll_user_inbox, user_id, company_id)
    return {
        "company_id": company_id,
        "emails_ingested": company_count + user_count,
        "company_inbox": company_count,
        "personal_inbox": user_count,
    }
