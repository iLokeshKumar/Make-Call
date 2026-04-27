"""SLO + dead-letter alert fan-out — SMTP and Slack.

Both channels are best-effort.  A failure on one never blocks the other.
Slack is a no-op when `SLACK_WEBHOOK_URL` env is unset; SMTP requires
the existing email_service config.

Format conventions:
  * SLO breach subject: "[SLO BREACH] {slo_id}: {actual} vs {target}"
  * Slack payload: simple {"text": "..."} blob (works with any incoming-webhook)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _format_message(slo_id: str, actual: Any, target: Any, severity: str) -> tuple[str, str]:
    """Return (subject, body) for a breach notification."""
    subject = f"[SLO {severity.upper()}] {slo_id}: actual={actual} target={target}"
    body = (
        f"SLO {slo_id} breached at threshold {target}.\n"
        f"Current value: {actual}\n"
        f"Severity: {severity}\n\n"
        f"Open /admin/slo-status for the full breakdown."
    )
    return subject, body


async def _post_slack(subject: str, body: str) -> bool:
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        # Common misconfig: pasted hooks.slack.com/... without the scheme.
        # Don't burn an httpx call + crash; warn once per breach.
        logger.warning("[alerts] SLACK_WEBHOOK_URL lacks http(s) scheme; ignoring (got %r)", url[:40])
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"text": f"*{subject}*\n```{body}```"})
        return resp.status_code < 400
    except Exception as exc:  # noqa: BLE001
        logger.warning("[alerts] Slack webhook failed: %s", exc)
        return False


def _send_smtp(subject: str, body: str, to_email: str | None = None) -> bool:
    """Send the alert via the existing SMTP path.  No-op when no recipient configured."""
    recipient = to_email or os.getenv("SLO_ALERT_EMAIL") or os.getenv("ADMIN_ALERT_EMAIL")
    if not recipient:
        return False
    try:
        from email_service import send_smtp_email
        return bool(send_smtp_email(
            to_email=recipient,
            subject=subject,
            body=body,
            html_body=None,
            company_name="Rio CRM",
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[alerts] SMTP send failed: %s", exc)
        return False


async def notify_breach(
    slo_id: str,
    actual: Any,
    target: Any,
    *,
    severity: str = "high",
    to_email: str | None = None,
) -> dict[str, bool]:
    """Fan out a breach alert to BOTH SMTP and Slack.

    Returns a dict {"slack": bool, "smtp": bool} reporting per-channel success.
    Channels with no configured recipient (no SLACK_WEBHOOK_URL / no SLO_ALERT_EMAIL)
    return False but don't raise.
    """
    subject, body = _format_message(slo_id, actual, target, severity)
    slack_task = asyncio.create_task(_post_slack(subject, body))
    smtp_ok = await asyncio.to_thread(_send_smtp, subject, body, to_email)
    slack_ok = await slack_task
    if slack_ok or smtp_ok:
        logger.info("[alerts] breach notify dispatched slo=%s slack=%s smtp=%s", slo_id, slack_ok, smtp_ok)
    return {"slack": slack_ok, "smtp": smtp_ok}


def notify_breach_sync(slo_id: str, actual: Any, target: Any, **kwargs: Any) -> dict[str, bool]:
    """Sync facade for the worker cycle (no event loop in scope)."""
    coro = notify_breach(slo_id, actual, target, **kwargs)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
