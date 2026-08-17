from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from utils.timezone_utils import (
    format_datetime_for_timezone,
    localize_datetime,
    parse_datetime_for_timezone,
    resolve_lead_timezone,
)


def test_resolve_lead_timezone_prefers_india_from_pincode_and_language():
    lead = SimpleNamespace(
        timezone=None,
        city=None,
        state=None,
        country=None,
        pincode="600001",
        preferred_language="hi",
        normalized_phone=None,
    )

    assert resolve_lead_timezone(lead) == "Asia/Kolkata"


def test_resolve_lead_timezone_uses_phone_country_code_when_geo_missing():
    lead = SimpleNamespace(
        timezone=None,
        city=None,
        state=None,
        country=None,
        pincode=None,
        preferred_language=None,
        normalized_phone="+918148749703",
    )

    assert resolve_lead_timezone(lead) == "Asia/Kolkata"


def test_localize_datetime_preserves_requested_wall_clock_for_naive_input():
    naive = datetime(2026, 5, 7, 17, 0, 0)

    localized = localize_datetime(naive, "Asia/Kolkata")

    assert localized.hour == 17
    assert localized.minute == 0
    assert localized.utcoffset().total_seconds() == 19800


def test_format_datetime_for_timezone_renders_local_human_time():
    dt = datetime(2026, 5, 7, 17, 0, 0)

    rendered = format_datetime_for_timezone(dt, "Asia/Kolkata")

    assert "5:00 PM" in rendered
    assert "IST" in rendered


def test_parse_datetime_for_timezone_treats_naive_booking_time_as_lead_local():
    parsed = parse_datetime_for_timezone("2026-08-14T10:00:00", "Asia/Kolkata")

    assert parsed.isoformat() == "2026-08-14T10:00:00+05:30"


def test_parse_datetime_for_timezone_rejects_mismatched_offset_for_local_booking_input():
    # A model that appends Z would otherwise turn 10:00 IST into 15:30 IST.
    try:
        parse_datetime_for_timezone(
            "2026-08-14T10:00:00Z",
            "Asia/Kolkata",
            require_local_wall_clock=True,
        )
    except ValueError as exc:
        assert "lead timezone" in str(exc)
    else:
        raise AssertionError("UTC timestamp must not be silently accepted for a local booking")
