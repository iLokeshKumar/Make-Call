from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import datetime
from typing import Any

# Country ISO-2 / common name → IANA timezone
_COUNTRY_TZ: dict[str, str] = {

    "IN": "Asia/Kolkata",  "INDIA": "Asia/Kolkata",
    "LK": "Asia/Colombo", "BD": "Asia/Dhaka", "PK": "Asia/Karachi",
    "NP": "Asia/Kathmandu",

    "SG": "Asia/Singapore", "MY": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",    "TH": "Asia/Bangkok",
    "ID": "Asia/Jakarta",   "VN": "Asia/Ho_Chi_Minh",
    "CN": "Asia/Shanghai",  "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",

    "AE": "Asia/Dubai",   "UAE": "Asia/Dubai",
    "SA": "Asia/Riyadh",  "QA": "Asia/Qatar",
    "KW": "Asia/Kuwait",  "BH": "Asia/Bahrain",
    "OM": "Asia/Muscat",  "JO": "Asia/Amman",
    "IL": "Asia/Jerusalem","EG": "Africa/Cairo",

    "GB": "Europe/London", "UK": "Europe/London",
    "IE": "Europe/Dublin", "PT": "Europe/Lisbon",
    "FR": "Europe/Paris",  "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam", "BE": "Europe/Brussels",
    "CH": "Europe/Zurich", "AT": "Europe/Vienna",
    "IT": "Europe/Rome",   "ES": "Europe/Madrid",
    "SE": "Europe/Stockholm", "NO": "Europe/Oslo",
    "DK": "Europe/Copenhagen", "FI": "Europe/Helsinki",
    "PL": "Europe/Warsaw", "CZ": "Europe/Prague",
    "RO": "Europe/Bucharest", "GR": "Europe/Athens",
    "TR": "Europe/Istanbul",  "RU": "Europe/Moscow",

    "US": "America/New_York",  "CA": "America/Toronto",
    "MX": "America/Mexico_City", "BR": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",  "CO": "America/Bogota",
    "PE": "America/Lima",

    "ZA": "Africa/Johannesburg", "NG": "Africa/Lagos",
    "KE": "Africa/Nairobi",
    "AU": "Australia/Sydney",  "NZ": "Pacific/Auckland",
}

# Indian state → IST (all same, but kept for extensibility with future UT offsets)
_INDIA_STATE_TZ: dict[str, str] = {
    s: "Asia/Kolkata" for s in [
        "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
        "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
        "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
        "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
        "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
        "andaman and nicobar", "chandigarh", "dadra", "daman", "delhi", "jammu",
        "kashmir", "ladakh", "lakshadweep", "puducherry",
    ]
}

_CITY_TZ: dict[str, str] = {
    "chennai": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata", "hyderabad": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata", "pune": "Asia/Kolkata", "ahmedabad": "Asia/Kolkata",
    "jaipur": "Asia/Kolkata", "surat": "Asia/Kolkata", "lucknow": "Asia/Kolkata",
    "kanpur": "Asia/Kolkata", "nagpur": "Asia/Kolkata", "patna": "Asia/Kolkata",
    "indore": "Asia/Kolkata", "thane": "Asia/Kolkata", "bhopal": "Asia/Kolkata",
    "visakhapatnam": "Asia/Kolkata", "coimbatore": "Asia/Kolkata", "kochi": "Asia/Kolkata",
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "sharjah": "Asia/Dubai",
    "singapore": "Asia/Singapore", "london": "Europe/London",
    "new york": "America/New_York", "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago", "toronto": "America/Toronto",
    "sydney": "Australia/Sydney", "tokyo": "Asia/Tokyo",
    "hong kong": "Asia/Hong_Kong", "shanghai": "Asia/Shanghai",
    "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "moscow": "Europe/Moscow", "istanbul": "Europe/Istanbul",
    "riyadh": "Asia/Riyadh", "doha": "Asia/Qatar",
}

_LANGUAGE_TZ: dict[str, str] = {
    # Strong default for Indian-market voice calls when geo is missing.
    "hi": "Asia/Kolkata",
    "ta": "Asia/Kolkata",
    "te": "Asia/Kolkata",
    "kn": "Asia/Kolkata",
    "mr": "Asia/Kolkata",
    "gu": "Asia/Kolkata",
    "bn": "Asia/Kolkata",
    "pa": "Asia/Kolkata",
    "ml": "Asia/Kolkata",
    "en-in": "Asia/Kolkata",
}


def detect_timezone(city: str | None, state: str | None, country: str | None) -> str:
    """
    Return IANA timezone string for a lead.  Never raises — falls back to
    DEFAULT_TIMEZONE env var (default Asia/Kolkata).
    Priority: city lookup → state lookup → country lookup → env default
    """
    if city:
        tz = _CITY_TZ.get(city.strip().lower())
        if tz:
            return tz

    if state:
        tz = _INDIA_STATE_TZ.get(state.strip().lower())
        if tz:
            return tz

    if country:
        key = country.strip().upper()
        tz = _COUNTRY_TZ.get(key)
        if not tz:
            # Try first two chars (handles "India", "IN", "United Arab Emirates" → "AE" fails, but "UAE" works)
            tz = _COUNTRY_TZ.get(key[:2])
        if tz:
            return tz

    return os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")


def infer_timezone_from_language(language: str | None) -> str | None:
    if not language:
        return None
    key = str(language).strip().lower()
    if not key:
        return None
    return _LANGUAGE_TZ.get(key) or _LANGUAGE_TZ.get(key.split("-", 1)[0])


def infer_timezone_from_pincode(pincode: str | None) -> str | None:
    if not pincode:
        return None
    digits = "".join(ch for ch in str(pincode) if ch.isdigit())
    if len(digits) == 6:
        return "Asia/Kolkata"
    return None


def infer_timezone_from_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    normalized = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    if normalized.startswith("+91") or normalized.startswith("91"):
        return "Asia/Kolkata"
    return None


def resolve_lead_timezone(
    lead: Any | None,
    *,
    session=None,
    company_id: int | None = None,
) -> str:
    """Resolve the best available timezone for a lead.

    Priority:
    1. lead.timezone
    2. lead city/state/country
    3. lead pincode
    4. lead preferred_language
    5. lead phone country code
    6. company login-history timezone
    7. DEFAULT_TIMEZONE
    """
    default_tz = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    if not lead:
        if session is not None and company_id:
            return get_company_timezone_from_login_history(session, company_id) or default_tz
        return default_tz

    tz = getattr(lead, "timezone", None)
    if tz:
        return tz

    tz = detect_timezone(
        getattr(lead, "city", None),
        getattr(lead, "state", None),
        getattr(lead, "country", None),
    )
    if tz != default_tz:
        return tz

    inferred = (
        infer_timezone_from_pincode(getattr(lead, "pincode", None))
        or infer_timezone_from_language(getattr(lead, "preferred_language", None))
        or infer_timezone_from_phone(getattr(lead, "normalized_phone", None))
    )
    if inferred:
        return inferred

    if session is not None and company_id:
        return get_company_timezone_from_login_history(session, company_id) or default_tz
    return default_tz


def localize_datetime(dt: datetime.datetime, timezone_str: str) -> datetime.datetime:
    """Attach/convert *dt* into the given timezone without losing the intended wall clock."""
    tz = ZoneInfo(timezone_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_datetime_for_timezone(
    value: str,
    timezone_str: str,
    *,
    require_local_wall_clock: bool = False,
) -> datetime.datetime:
    """Parse a scheduling timestamp using an explicit timezone contract.

    Scheduling tools receive a lead-local wall-clock value (for example,
    ``2026-08-14T10:00:00``).  A naive timestamp is therefore attached to the
    lead timezone; it must never be assumed to be UTC.  Callers that use the
    local-wall-clock contract can reject offsets because a model adding ``Z``
    would silently move a 10:00 IST booking to 15:30 IST.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("A meeting date/time is required")
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO meeting date/time: {value!r}") from exc

    if parsed.tzinfo is not None:
        if require_local_wall_clock:
            expected = parsed.astimezone(ZoneInfo(timezone_str))
            # A timestamp with an offset is safe only when that offset agrees
            # with the lead's runtime timezone at that date (DST included).
            # This catches models that append Z to a local wall-clock value.
            wall_clock = parsed.replace(tzinfo=None)
            if wall_clock != expected.replace(tzinfo=None):
                raise ValueError(
                    f"Meeting time offset does not match the lead timezone {timezone_str}; "
                    "send the lead-local wall-clock time"
                )
            return expected
        return parsed.astimezone(ZoneInfo(timezone_str))

    return parsed.replace(tzinfo=ZoneInfo(timezone_str))


def format_datetime_for_timezone(
    dt: datetime.datetime | None,
    timezone_str: str,
    *,
    include_timezone: bool = True,
) -> str:
    if not dt:
        return ""
    localized = localize_datetime(dt, timezone_str)
    fmt = "%B %d, %Y %I:%M %p"
    rendered = localized.strftime(fmt).replace(" 0", " ")
    if include_timezone:
        rendered = f"{rendered} {localized.tzname() or timezone_str}"
    return rendered


def get_company_timezone_from_login_history(session, company_id: int) -> str | None:
    """
    Resolve timezone from the most recent login_history geo_data for any user
    in the given company.  Returns IANA timezone string or None.
    """
    from sqlmodel import select
    from models.models import LoginHistory

    row = session.exec(
        select(LoginHistory.geo_data)
        .where(
            LoginHistory.company_id == company_id,
            LoginHistory.geo_data.is_not(None),
        )
        .order_by(LoginHistory.created_at.desc())
        .limit(1)
    ).first()
    if row and isinstance(row, dict):
        return row.get("timezone")
    return None


# Defaults are re-read every call so env changes take effect without restart in dev.  Cheap: two dict lookups per guard invocation.
_BUSINESS_START_DEFAULT = 9
_BUSINESS_END_DEFAULT = 22
_SUNDAY_BLOCKED_DEFAULT = True


def _parse_int(raw, default: int) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_bool(raw, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def business_hours_config_for_company(session, company_id: int | None) -> dict:
    """Resolve the effective business-hours config for *company_id*.

    Priority: CompanySetting (if company_id supplied + session live) → env vars
    → hard-coded defaults.  Never raises — any lookup failure falls through.
    Callers get a dict: {start, end, sunday_blocked, disabled}.
    """
    start = _parse_int(os.getenv("BUSINESS_HOURS_START"), _BUSINESS_START_DEFAULT)
    end = _parse_int(os.getenv("BUSINESS_HOURS_END"), _BUSINESS_END_DEFAULT)
    sunday_blocked = _parse_bool(os.getenv("BUSINESS_SUNDAY_BLOCKED"), _SUNDAY_BLOCKED_DEFAULT)
    disabled = _parse_bool(os.getenv("DISABLE_BUSINESS_HOURS_GUARD"), False)

    if session is not None and company_id:
        try:
            from credentials_service import get_company_setting_value
            cs = get_company_setting_value
            v = cs(session, company_id, "BUSINESS_HOURS_START")
            start = _parse_int(v, start)
            v = cs(session, company_id, "BUSINESS_HOURS_END")
            end = _parse_int(v, end)
            v = cs(session, company_id, "BUSINESS_SUNDAY_BLOCKED")
            sunday_blocked = _parse_bool(v, sunday_blocked)
            v = cs(session, company_id, "DISABLE_BUSINESS_HOURS_GUARD")
            disabled = _parse_bool(v, disabled)
        except Exception:
            pass

    return {
        "start": start,
        "end": end,
        "sunday_blocked": sunday_blocked,
        "disabled": disabled,
    }


def is_within_business_hours(
    timezone_str: str,
    *,
    start_hour: int | None = None,
    end_hour: int | None = None,
    sunday_blocked: bool | None = None,
    disabled: bool | None = None,
) -> bool:
    """Return True if it is currently between start_hour and end_hour (exclusive)
    in the given IANA timezone.

    Defaults read from env (when the caller does not pass overrides):
      * BUSINESS_HOURS_START (default 9)
      * BUSINESS_HOURS_END   (default 22)
      * BUSINESS_SUNDAY_BLOCKED (default 1 — block Sundays)
      * DISABLE_BUSINESS_HOURS_GUARD (default 0) — when 1, always returns True

    Callers with access to a DB session should use
    business_hours_config_for_company() to pick up per-company overrides
    from CompanySetting, then pass them in via the kwargs above.

    Falls back to True (allow call) on any error so a bad timezone string
    never silently blocks all calls.
    """
    eff_disabled = (
        disabled if disabled is not None
        else _parse_bool(os.getenv("DISABLE_BUSINESS_HOURS_GUARD"), False)
    )
    if eff_disabled:
        return True

    start = start_hour if start_hour is not None else _parse_int(os.getenv("BUSINESS_HOURS_START"), _BUSINESS_START_DEFAULT)
    end = end_hour if end_hour is not None else _parse_int(os.getenv("BUSINESS_HOURS_END"), _BUSINESS_END_DEFAULT)
    eff_sunday_blocked = (
        sunday_blocked if sunday_blocked is not None
        else _parse_bool(os.getenv("BUSINESS_SUNDAY_BLOCKED"), _SUNDAY_BLOCKED_DEFAULT)
    )

    try:
        tz = ZoneInfo(timezone_str)
        now = datetime.datetime.now(tz)
        if eff_sunday_blocked and now.weekday() == 6:
            return False
        return start <= now.hour < end
    except (ZoneInfoNotFoundError, Exception):
        return True
