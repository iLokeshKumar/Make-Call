"""
Lightweight IP geolocation using ip-api.com (free, no API key).
Returns an approximate "City, Region, Country" string.

Rate limit: 45 req/min on the free HTTP endpoint — sufficient for login events.
Private/loopback IPs resolve immediately without a network call.
"""

import ipaddress
import logging
import asyncio

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

_IP_API_URL = "http://ip-api.com/json/{ip}?fields=status,city,regionName,country"


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


async def resolve_location(ip: str | None) -> str:
    """
    Return an approximate location string for *ip*.
    Never raises — returns "Unknown" on any failure.
    """
    if not ip:
        return "Unknown"
    ip = ip.strip()
    if _is_private(ip):
        return "Local / Private network"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _IP_API_URL.format(ip=ip),
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                if resp.status != 200:
                    return "Unknown"
                data = await resp.json()
                if data.get("status") != "success":
                    return "Unknown"
                parts = [data.get("city"), data.get("regionName"), data.get("country")]
                location = ", ".join(p for p in parts if p)
                return location or "Unknown"
    except asyncio.TimeoutError:
        logger.debug("geoip timeout for %s", ip)
        return "Unknown"
    except Exception as exc:
        logger.debug("geoip failed for %s: %s", ip, exc)
        return "Unknown"
