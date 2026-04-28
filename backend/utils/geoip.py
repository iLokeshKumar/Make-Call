"""
Lightweight IP geolocation using ip-api.com (free, no API key).

Fields requested: city, region, country, timezone, ISP, proxy/mobile/hosting flags.
Rate limit: 45 req/min on the free HTTP endpoint — sufficient for login events.
Private/loopback IPs fall back to the server's own public IP so logs always
carry some geography (useful in dev; in prod the real IP comes via X-Forwarded-For).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import TypedDict

import aiohttp

logger = logging.getLogger(__name__)

_PRIVATE_RANGES = (
    "127.",
    "::1",
    "10.",
    "192.168.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "fc", "fd",  # IPv6 private
)

# All fields we care about — drives both the query string and what we store.
_FIELDS = "status,city,regionName,country,countryCode,timezone,isp,org,proxy,mobile,hosting,lat,lon,query"

_IP_API_URL = f"http://ip-api.com/json/{{ip}}?fields={_FIELDS}"
_IP_API_SELF_URL = f"http://ip-api.com/json/?fields={_FIELDS}"


class GeoResult(TypedDict):
    location: str        # Human-readable "City, Region, Country"
    geo_data: dict       # Full response for storage / alerting


def _is_private(ip: str) -> bool:
    if not ip:
        return True
    ip = ip.strip()
    for prefix in _PRIVATE_RANGES:
        if ip.startswith(prefix):
            return True
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _parse(data: dict, server_fallback: bool = False) -> GeoResult:
    """Turn a successful ip-api response into a GeoResult."""
    parts = [data.get("city"), data.get("regionName"), data.get("country")]
    location = ", ".join(p for p in parts if p) or "Unknown"
    if server_fallback:
        location = f"{location} (server)"

    geo_data = {
        "city":         data.get("city"),
        "region":       data.get("regionName"),
        "country":      data.get("country"),
        "country_code": data.get("countryCode"),
        "timezone":     data.get("timezone"),
        "isp":          data.get("isp"),
        "org":          data.get("org"),
        "is_proxy":     data.get("proxy", False),
        "is_mobile":    data.get("mobile", False),
        "is_hosting":   data.get("hosting", False),
        "lat":          data.get("lat"),
        "lon":          data.get("lon"),
        "query_ip":     data.get("query"),
    }
    return GeoResult(location=location, geo_data=geo_data)


async def _fetch(url: str, server_fallback: bool = False) -> GeoResult | None:
    """Return a GeoResult or None on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("status") != "success":
                    return None
                return _parse(data, server_fallback=server_fallback)
    except asyncio.TimeoutError:
        logger.debug("geoip timeout for %s", url)
        return None
    except Exception as exc:
        logger.debug("geoip error for %s: %s", url, exc)
        return None


_UNKNOWN: GeoResult = GeoResult(location="Unknown", geo_data={})


async def resolve_location(ip: str | None) -> GeoResult:
    """
    Return a GeoResult for *ip*.

    For private/loopback IPs falls back to the server's own public IP —
    ensures logs always carry some geography even in local dev.
    Never raises.
    """
    if not ip:
        return _UNKNOWN
    ip = ip.strip()

    if _is_private(ip):
        result = await _fetch(_IP_API_SELF_URL, server_fallback=True)
        return result or _UNKNOWN

    result = await _fetch(_IP_API_URL.format(ip=ip))
    return result or _UNKNOWN
