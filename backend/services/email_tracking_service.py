"""
Email tracking — token generation, pixel/URL builders, link rewriting.
Pure utility functions; DB writes are limited to token minting.
"""
from __future__ import annotations

import re
from secrets import token_urlsafe
from urllib.parse import quote

from sqlmodel import Session

from models.models import Interaction, utc_now

TRACKABLE_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def generate_tracking_token() -> str:
    return token_urlsafe(24)


def ensure_interaction_tracking_token(
    session: Session, interaction: Interaction, token_key: str = "tracking_token"
) -> str:
    metadata = interaction.metadata_json or {}
    token = metadata.get(token_key)
    if not token:
        token = generate_tracking_token()
        metadata[token_key] = token
        interaction.metadata_json = metadata
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
    return token


def build_open_tracking_pixel(tracking_base_url: str, token: str) -> str:
    return (
        f'<img src="{tracking_base_url.rstrip("/")}/tracking/email/open/{token}" '
        'alt="" width="1" height="1" style="display:none;" />'
    )


def build_email_click_tracking_url(tracking_base_url: str, token: str, target_url: str) -> str:
    encoded_target = quote(target_url, safe="")
    return f"{tracking_base_url.rstrip('/')}/tracking/email/click/{token}?target={encoded_target}"


def rewrite_click_tracking_links(body: str, tracking_base_url: str, token: str) -> str:
    if not body or not token:
        return body

    tracking_prefix = f"{tracking_base_url.rstrip('/')}/tracking/email/click/"

    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        if url.startswith(tracking_prefix):
            return url
        return build_email_click_tracking_url(tracking_base_url, token, url)

    return TRACKABLE_URL_RE.sub(replace, body)


def build_unsubscribe_url(tracking_base_url: str, token: str, channel: str) -> str:
    return (
        f"{tracking_base_url.rstrip('/')}/tracking/unsubscribe"
        f"?token={quote(token, safe='')}&channel={quote(channel, safe='')}"
    )


def build_quote_view_url(tracking_base_url: str, token: str) -> str:
    return f"{tracking_base_url.rstrip('/')}/tracking/quote/view/{token}"
