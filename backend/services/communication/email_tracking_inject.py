"""
Inject open-pixel and click-wrapping into outbound email HTML.

The existing routes at /tracking/email/open/{token} and
/tracking/email/click/{token}?target=<url> (routes/tracking.py) handle the
server side. This module only handles HTML mutation before send.
"""
from __future__ import annotations

import re
import urllib.parse
from uuid import uuid4

_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.IGNORECASE)

_TRANSPARENT_GIF_PIXEL = (
    '<img src="{base_url}/tracking/email/open/{token}" '
    'width="1" height="1" alt="" style="display:none;border:0;" />'
)


def generate_tracking_token() -> str:
    return str(uuid4())


def generate_unsubscribe_url(tracking_token: str, base_url: str) -> str:
    return (
        f"{base_url}/tracking/unsubscribe"
        f"?token={tracking_token}&channel=email"
    )


def inject_email_tracking(html: str, tracking_token: str, base_url: str) -> str:
    """
    1. Wrap every http(s) href with the click-tracking redirect.
    2. Append a 1x1 transparent-GIF open-tracking pixel before </body>.

    Safe to call on already-wrapped HTML (idempotent because /tracking/
    URLs are skipped by the regex guard).
    """
    click_base = f"{base_url}/tracking/email/click/{tracking_token}"

    def _wrap_href(m: re.Match) -> str:
        original_url = m.group(1)
        # Don't double-wrap tracking or unsubscribe URLs
        if "/tracking/" in original_url:
            return m.group(0)
        encoded = urllib.parse.quote(original_url, safe="")
        return f'href="{click_base}?target={encoded}"'

    html = _HREF_RE.sub(_wrap_href, html)

    pixel = _TRANSPARENT_GIF_PIXEL.format(base_url=base_url, token=tracking_token)

    if "</body>" in html.lower():
        html = re.sub(r"</body>", f"{pixel}</body>", html, flags=re.IGNORECASE, count=1)
    else:
        html = html + pixel

    return html
