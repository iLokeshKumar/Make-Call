"""Pure CSRF double-submit logic — no network, DB, or framework imports.

The middleware in main.py uses this module. Keeping it stdlib-only means the
invariants are unit-testable without loading the full auth stack (pyotp, bcrypt,
fastapi.security, etc.), and a future security refactor can reason about the
CSRF surface in isolation.

The session cookie + auth surface still lives in auth.py. This module is only
the algorithm.
"""
from __future__ import annotations

import secrets
from typing import Optional


SESSION_COOKIE_NAME = "rio_session"
CSRF_COOKIE_NAME = "rio_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Paths where CSRF enforcement is bypassed. Rationale per entry:
#   /token, /companies/register — no session yet, nothing to forge.
#   /auth/logout                — self-limiting; max damage is unintended logout.
#   /tracking, /q, /quote,      — public endpoints authenticated by URL token,
#   /invite/accept,               not by our session cookie.
#   /feedback/csat/
#   /health, /docs, /openapi,   — meta-endpoints with no mutation surface.
#   /redoc, /uploads, /static
#
# External webhooks are NOT listed here. They're handled implicitly: this function only enforces CSRF when a session cookie is present, and webhooks never carry our session cookie.
CSRF_BYPASS_PREFIXES: tuple[str, ...] = (
    # Meta / static surface
    "/health", "/docs", "/openapi", "/redoc", "/uploads", "/static",

    # Auth entry / exit — no session yet, or self-limiting worst case
    "/token", "/companies/register", "/auth/logout",

    # Email-verification flow. New users click a link — their browser may or may not have a stale session cookie; either way the flow should work.
    "/verify-email", "/auth/verify-email",

    # Google OAuth callback — POST from the Rio frontend after Google's redirect hands back a code. The user is usually logged in, so the session cookie comes along, but the OAuth frontend code path doesn't attach CSRF.
    "/google/callback", "/auth/google/callback",

    # Invite acceptance — public page, token in URL. Backend route is /invites (plural) — both forms listed defensively in case either is reached.
    "/invites/accept", "/auth/invites/accept", "/invite/accept",

    # Public tracking / quote / CSAT — URL-token auth, not session auth.
    "/tracking/", "/q/", "/quote/", "/feedback/csat/",
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def generate_csrf_token() -> str:
    """Cryptographically random URL-safe CSRF token (256 bits)."""
    return secrets.token_urlsafe(32)


def verify_csrf_invariants(
    method: str,
    path: str,
    session_cookie: Optional[str],
    csrf_cookie: Optional[str],
    csrf_header: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Return (ok, reason). ok=True means the request may proceed.

    Layering:
      1. Safe methods (GET/HEAD/OPTIONS) pass — no state change possible.
      2. CSRF_BYPASS_PREFIXES pass.
      3. No session cookie = bearer-only (or anonymous) → CSRF N/A: an attacker
         who can't set Authorization can't set X-CSRF-Token either.
      4. Otherwise require both cookie + header AND that they match in
         constant time (secrets.compare_digest).
    """
    if method.upper() in _SAFE_METHODS:
        return True, None

    if any(path.startswith(p) for p in CSRF_BYPASS_PREFIXES):
        return True, None

    if not session_cookie:
        return True, None

    if not csrf_header or not csrf_cookie:
        return False, "CSRF token missing"

    if not secrets.compare_digest(csrf_header, csrf_cookie):
        return False, "CSRF token mismatch"

    return True, None
