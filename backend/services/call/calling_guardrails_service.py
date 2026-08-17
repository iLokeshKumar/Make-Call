"""Calling guardrails — time window enforcement for outbound calls.

Supports per-agent configurable time windows, timezone resolution from
phone/area code, auto-reschedule to next allowed slot, and urgent bypass.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 22
DEFAULT_SUNDAY_BLOCKED = True

# Country → IANA timezone mapping for phone country codes
COUNTRY_CODE_TZ: dict[str, str] = {
    "91": "Asia/Kolkata",
    "1": "America/New_York",
    "44": "Europe/London",
    "61": "Australia/Sydney",
    "65": "Asia/Singapore",
    "971": "Asia/Dubai",
    "966": "Asia/Riyadh",
    "974": "Asia/Qatar",
    "968": "Asia/Muscat",
    "973": "Asia/Bahrain",
    "20": "Africa/Cairo",
    "27": "Africa/Johannesburg",
    "234": "Africa/Lagos",
    "254": "Africa/Nairobi",
    "233": "Africa/Accra",
    "212": "Africa/Casablanca",
    "216": "Africa/Tunis",
    "213": "Africa/Algiers",
    "33": "Europe/Paris",
    "49": "Europe/Berlin",
    "39": "Europe/Rome",
    "34": "Europe/Madrid",
    "351": "Europe/Lisbon",
    "31": "Europe/Amsterdam",
    "32": "Europe/Brussels",
    "41": "Europe/Zurich",
    "46": "Europe/Stockholm",
    "47": "Europe/Oslo",
    "45": "Europe/Copenhagen",
    "358": "Europe/Helsinki",
    "48": "Europe/Warsaw",
    "420": "Europe/Prague",
    "36": "Europe/Budapest",
    "40": "Europe/Bucharest",
    "30": "Europe/Athens",
    "7": "Europe/Moscow",
    "81": "Asia/Tokyo",
    "82": "Asia/Seoul",
    "86": "Asia/Shanghai",
    "852": "Asia/Hong_Kong",
    "886": "Asia/Taipei",
    "60": "Asia/Kuala_Lumpur",
    "63": "Asia/Manila",
    "62": "Asia/Jakarta",
    "66": "Asia/Bangkok",
    "84": "Asia/Ho_Chi_Minh",
    "92": "Asia/Karachi",
    "880": "Asia/Dhaka",
    "977": "Asia/Kathmandu",
    "94": "Asia/Colombo",
    "95": "Asia/Yangon",
    "98": "Asia/Tehran",
    "55": "America/Sao_Paulo",
    "52": "America/Mexico_City",
    "54": "America/Argentina/Buenos_Aires",
    "56": "America/Santiago",
    "57": "America/Bogota",
    "51": "America/Lima",
    "58": "America/Caracas",
    "507": "America/Panama",
    "506": "America/Costa_Rica",
    "502": "America/Guatemala",
    "503": "America/El_Salvador",
    "504": "America/Tegucigalpa",
    "505": "America/Managua",
    "593": "America/Guayaquil",
    "591": "America/La_Paz",
    "595": "America/Asuncion",
    "598": "America/Montevideo",
}


def timezone_for_phone(phone: str) -> str | None:
    """Resolve IANA timezone from phone number country code.

    Strips leading '+' and matches against known country codes
    (longest prefix match). Returns None if unknown.
    """
    if not phone:
        return None
    cleaned = phone.lstrip("+").strip()
    if not cleaned:
        return None
    for code_len in (3, 2, 1):
        if len(cleaned) >= code_len:
            prefix = cleaned[:code_len]
            tz = COUNTRY_CODE_TZ.get(prefix)
            if tz:
                return tz
    return None


class CallingGuardrails:
    """Per-agent calling guardrails for time window enforcement.

    Typical usage:
        guardrails = CallingGuardrails(config_dict)
        ok, reason = guardrails.is_allowed_for_timezone("Asia/Kolkata")
        if not ok:
            next_at = guardrails.get_next_allowed_time("Asia/Kolkata")
    """

    def __init__(
        self,
        agent_config: dict | None = None,
        company_config: dict | None = None,
    ):
        cfg = agent_config or {}
        self.start_hour: int = cfg.get("start_hour", DEFAULT_START_HOUR)
        self.end_hour: int = cfg.get("end_hour", DEFAULT_END_HOUR)
        self.sunday_blocked: bool = cfg.get("sunday_blocked", DEFAULT_SUNDAY_BLOCKED)
        self.bypass_urgent: bool = cfg.get("bypass_urgent", False)
        self.enabled: bool = cfg.get("enabled", False)

        if company_config:
            self.start_hour = cfg.get("start_hour") or company_config.get("start", self.start_hour)
            self.end_hour = cfg.get("end_hour") or company_config.get("end", self.end_hour)
            self.sunday_blocked = cfg.get("sunday_blocked", company_config.get("sunday_blocked", self.sunday_blocked))

    def is_allowed(self, timezone_str: str, *, urgent: bool = False) -> tuple[bool, str | None]:
        """Check if calling is allowed now in the given timezone.

        Returns (allowed: bool, reason: str | None).
        If `urgent=True` and `bypass_urgent` is enabled, always returns True.
        """
        if not self.enabled:
            return True, None

        if urgent and self.bypass_urgent:
            return True, None

        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(timezone_str))

            if self.sunday_blocked and now.weekday() == 6:
                return False, "sunday_blocked"

            if not (self.start_hour <= now.hour < self.end_hour):
                return False, f"outside_window:{self.start_hour}-{self.end_hour}"

            return True, None

        except Exception as exc:
            logger.warning("[Guardrails] Timezone check failed for %s: %s", timezone_str, exc)
            return True, None

    def is_allowed_for_phone(self, phone: str, *, urgent: bool = False) -> tuple[bool, str | None]:
        """Check if calling is allowed for a phone number.

        Resolves timezone from the phone number's country code.
        """
        tz = timezone_for_phone(phone)
        if not tz:
            return True, None
        return self.is_allowed(tz, urgent=urgent)

    def get_next_allowed_time(self, timezone_str: str) -> datetime.datetime | None:
        """Calculate the next allowed calling time in the given timezone.

        Returns a datetime in the given timezone, or None if guardrails are disabled.
        """
        if not self.enabled:
            return None

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(timezone_str)
            now = datetime.datetime.now(tz)

            if self.sunday_blocked and now.weekday() == 6:
                days_ahead = 1
                next_day = now + datetime.timedelta(days=days_ahead)
                return next_day.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)

            current_hour = now.hour
            if current_hour < self.start_hour:
                return now.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
            elif current_hour >= self.end_hour:
                next_day = now + datetime.timedelta(days=1)
                if self.sunday_blocked and next_day.weekday() == 6:
                    next_day += datetime.timedelta(days=1)
                return next_day.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)

            return now

        except Exception as exc:
            logger.warning("[Guardrails] Next-allowed-time failed for %s: %s", timezone_str, exc)
            return None

    def get_next_allowed_for_phone(self, phone: str) -> datetime.datetime | None:
        """Calculate next allowed time for a phone number."""
        tz = timezone_for_phone(phone)
        if not tz:
            return None
        return self.get_next_allowed_time(tz)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "sunday_blocked": self.sunday_blocked,
            "bypass_urgent": self.bypass_urgent,
        }
