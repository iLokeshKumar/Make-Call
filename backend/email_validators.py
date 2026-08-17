import os
from typing import Optional

import httpx
import MailChecker

CONSUMER_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "outlook.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "tutanota.com", "fastmail.com",
    "zoho.com", "gmx.com", "gmx.net", "inbox.com", "mail.com", "hushmail.com",
}


async def validate_email_domain(email: str) -> Optional[str]:
    """Returns an error string if the email domain is not allowed, None if OK."""
    domain = email.split("@")[-1].lower()

    if domain in CONSUMER_DOMAINS:
        return (
            "Personal email addresses are not allowed. "
            "Please sign up with your company or work email."
        )

    if not MailChecker.MailChecker.is_valid(email):
        return (
            "Disposable or temporary email addresses are not allowed. "
            "Please use your work email."
        )

    disify_key = os.getenv("DISIFY_API_KEY", "")
    try:
        headers = {"Authorization": f"Bearer {disify_key}"} if disify_key else {}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"https://www.disify.com/api/email/{email}",
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("disposable"):
                return (
                    "Disposable or temporary email addresses are not allowed. "
                    "Please use your work email."
                )
            if not data.get("dns", True):
                return (
                    "This email domain does not appear to be valid. "
                    "Please check your email address."
                )
    except (httpx.TimeoutException, httpx.RequestError):
        pass  # Disify unavailable — mailchecker already ran, proceed

    return None
