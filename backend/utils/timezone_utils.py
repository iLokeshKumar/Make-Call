from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import datetime

# Country ISO-2 / common name → IANA timezone
_COUNTRY_TZ: dict[str, str] = {
    # South Asia
    "IN": "Asia/Kolkata",  "INDIA": "Asia/Kolkata",
    "LK": "Asia/Colombo", "BD": "Asia/Dhaka", "PK": "Asia/Karachi",
    "NP": "Asia/Kathmandu",
    # Southeast / East Asia
    "SG": "Asia/Singapore", "MY": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",    "TH": "Asia/Bangkok",
    "ID": "Asia/Jakarta",   "VN": "Asia/Ho_Chi_Minh",
    "CN": "Asia/Shanghai",  "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    # Middle East
    "AE": "Asia/Dubai",   "UAE": "Asia/Dubai",
    "SA": "Asia/Riyadh",  "QA": "Asia/Qatar",
    "KW": "Asia/Kuwait",  "BH": "Asia/Bahrain",
    "OM": "Asia/Muscat",  "JO": "Asia/Amman",
    "IL": "Asia/Jerusalem","EG": "Africa/Cairo",
    # Europe
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
    # Americas
    "US": "America/New_York",  "CA": "America/Toronto",
    "MX": "America/Mexico_City", "BR": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",  "CO": "America/Bogota",
    "PE": "America/Lima",
    # Africa / Oceania
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

# Well-known city → timezone for ambiguous cases
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


_BUSINESS_START = 9   # 09:00 local
_BUSINESS_END   = 20  # 20:00 local  (8 pm)


def is_within_business_hours(
    timezone_str: str,
    *,
    start_hour: int = _BUSINESS_START,
    end_hour: int   = _BUSINESS_END,
) -> bool:
    """
    Return True if it is currently between start_hour and end_hour (exclusive)
    in the given IANA timezone.  Treats Monday–Saturday as working days;
    Sunday is blocked.  Falls back to True (allow call) on any error so that
    a bad timezone string never silently blocks all calls.
    """
    try:
        tz   = ZoneInfo(timezone_str)
        now  = datetime.datetime.now(tz)
        if now.weekday() == 6:
            return False
        return start_hour <= now.hour < end_hour
    except (ZoneInfoNotFoundError, Exception):
        return True
