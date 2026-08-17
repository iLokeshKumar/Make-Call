"""Invariant tests for CSRF double-submit protection.

The middleware lives in main.py but the decision is in the pure function
`auth.verify_csrf_invariants`, so we test that directly. If the function
says pass/fail, the middleware does the same — it's just a dispatcher.

The five invariants these tests lock down:
  1. Safe methods (GET/HEAD/OPTIONS) always pass — no state change possible.
  2. Bypass paths (login, public token routes) always pass.
  3. Bearer-only requests (no session cookie) always pass — CSRF is moot.
  4. State-changing cookie-auth requests fail without matching header.
  5. Matching header + cookie passes, mismatched fails, constant-time compare.

If any of these breaks, the agent loses either a security property (CSRF bypass
trivially achievable) or an availability property (legitimate requests get 403'd).
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest

from csrf import (
    CSRF_BYPASS_PREFIXES,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    generate_csrf_token,
    verify_csrf_invariants,
)


# Invariant 1: safe methods always pass

class TestSafeMethodsAlwaysPass:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get", "head", "options"])
    def test_safe_method_passes_even_without_any_tokens(self, method):
        ok, reason = verify_csrf_invariants(
            method=method, path="/leads/42",
            session_cookie="jwt-here", csrf_cookie=None, csrf_header=None,
        )
        assert ok is True
        assert reason is None

    def test_safe_method_passes_even_with_mismatched_tokens(self):
        # Mismatch should not matter for safe methods
        ok, _ = verify_csrf_invariants(
            method="GET", path="/leads/42",
            session_cookie="jwt", csrf_cookie="A", csrf_header="B",
        )
        assert ok is True


# Invariant 2: bypass paths always pass

class TestBypassPathsAlwaysPass:
    @pytest.mark.parametrize("path", [
        "/token",                          # login
        "/companies/register",             # register
        "/auth/logout",                    # logout (self-limiting)
        "/tracking/quote/accept/abc123",   # public quote accept via URL token
        "/q/abc123",                       # public quote view
        "/quote/abc123",                   # public quote page
        "/invite/accept",                  # legacy singular path (safety)
        "/invites/accept",                 # actual backend route (plural)
        "/auth/invites/accept",            # alias under /auth
        "/feedback/csat/xyz",              # public CSAT submission
        "/verify-email",                   # email verification link
        "/auth/verify-email",              # alias under /auth
        "/google/callback",                # OAuth callback from Google
        "/auth/google/callback",           # alias under /auth
        "/health",
        "/docs",
    ])
    def test_bypass_path_passes_state_changing_without_csrf(self, path):
        ok, _ = verify_csrf_invariants(
            method="POST", path=path,
            session_cookie="jwt-here", csrf_cookie=None, csrf_header=None,
        )
        assert ok is True

    def test_non_bypass_path_does_not_pass(self):
        # Sanity: a normal authenticated POST without CSRF fails
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie=None, csrf_header=None,
        )
        assert ok is False
        assert "missing" in reason.lower()


# Invariant 3: bearer-only requests (no session cookie) always pass

class TestBearerOnlyPasses:
    """Clients that authenticate via Authorization header (no cookies) are not
    subject to CSRF — the attacker can't set the Authorization header either.
    This keeps the 170+ legacy fetches working during the migration.
    """

    def test_no_session_cookie_passes_state_changing(self):
        ok, _ = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie=None, csrf_cookie=None, csrf_header=None,
        )
        assert ok is True

    def test_no_session_cookie_passes_even_with_bogus_csrf(self):
        # Header and cookie are ignored when session cookie is absent
        ok, _ = verify_csrf_invariants(
            method="DELETE", path="/leads/42",
            session_cookie=None, csrf_cookie="A", csrf_header="B",
        )
        assert ok is True


# Invariant 4: missing CSRF tokens fail

class TestMissingTokensFail:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_missing_header_fails(self, method):
        ok, reason = verify_csrf_invariants(
            method=method, path="/leads",
            session_cookie="jwt", csrf_cookie="valid-token", csrf_header=None,
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_missing_cookie_fails(self):
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie=None, csrf_header="valid-token",
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_both_missing_fails(self):
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie=None, csrf_header=None,
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_empty_strings_fail(self):
        # Empty string should be treated as missing, not as a valid match
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie="", csrf_header="",
        )
        assert ok is False
        assert "missing" in reason.lower()


# Invariant 5: matching passes, mismatched fails (constant-time compare)

class TestMatchBehavior:
    def test_matching_tokens_pass(self):
        token = generate_csrf_token()
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie=token, csrf_header=token,
        )
        assert ok is True
        assert reason is None

    def test_mismatched_tokens_fail(self):
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt",
            csrf_cookie=generate_csrf_token(),
            csrf_header=generate_csrf_token(),
        )
        assert ok is False
        assert "mismatch" in reason.lower()

    def test_same_prefix_different_tail_fails(self):
        # Guard against a naive startswith/length-based comparison
        ok, reason = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt",
            csrf_cookie="abcdefgh1234567890",
            csrf_header="abcdefgh1234567891",
        )
        assert ok is False
        assert "mismatch" in reason.lower()

    def test_header_longer_than_cookie_fails(self):
        ok, _ = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt",
            csrf_cookie="abc",
            csrf_header="abcdef",
        )
        assert ok is False

    def test_case_sensitive_match(self):
        # CSRF tokens are case-sensitive; "abc" must not match "ABC"
        ok, _ = verify_csrf_invariants(
            method="POST", path="/leads",
            session_cookie="jwt", csrf_cookie="abc123", csrf_header="ABC123",
        )
        assert ok is False


# Bonus: token generator properties

class TestGenerateCsrfToken:
    def test_token_is_nonempty(self):
        assert len(generate_csrf_token()) > 0

    def test_token_is_url_safe(self):
        # secrets.token_urlsafe should only contain URL-safe base64 characters
        t = generate_csrf_token()
        assert all(c.isalnum() or c in "-_" for c in t), f"non-URL-safe char in {t!r}"

    def test_tokens_are_unique(self):
        # 100 consecutive tokens should all be distinct (cryptographically random)
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_token_has_enough_entropy(self):
        # 32 bytes URL-safe-encoded is ~43 characters; we want comfortably >30
        assert len(generate_csrf_token()) >= 32


# Surface-level regression: the constants exist and have expected values

class TestExportedConstants:
    """These names are imported by main.py's middleware. If they're renamed or
    removed, the middleware will fail at import time and CI catches it — but
    an explicit test makes the contract visible.
    """

    def test_cookie_names_are_defined(self):
        assert SESSION_COOKIE_NAME == "rio_session"
        assert CSRF_COOKIE_NAME == "rio_csrf"

    def test_header_name_is_defined(self):
        assert CSRF_HEADER_NAME == "X-CSRF-Token"

    def test_bypass_includes_login_and_public_quote_paths(self):
        assert "/token" in CSRF_BYPASS_PREFIXES
        assert "/companies/register" in CSRF_BYPASS_PREFIXES
        assert "/auth/logout" in CSRF_BYPASS_PREFIXES
        assert any(p.startswith("/tracking") for p in CSRF_BYPASS_PREFIXES)
        assert any(p.startswith("/q") for p in CSRF_BYPASS_PREFIXES)

    def test_bypass_includes_email_verification_and_oauth_callback(self):
        # Added after the first review found these missing. A regression here
        # means a logged-in user who triggers the verify / OAuth flows could
        # get 403'd unexpectedly.
        assert "/verify-email" in CSRF_BYPASS_PREFIXES
        assert "/auth/verify-email" in CSRF_BYPASS_PREFIXES
        assert "/google/callback" in CSRF_BYPASS_PREFIXES
        assert "/auth/google/callback" in CSRF_BYPASS_PREFIXES

    def test_bypass_covers_both_invite_path_spellings(self):
        # Backend route is /invites/accept (plural); /invite/accept is retained
        # as a defensive alias because the frontend path uses the singular form.
        assert "/invites/accept" in CSRF_BYPASS_PREFIXES
        assert "/invite/accept" in CSRF_BYPASS_PREFIXES
