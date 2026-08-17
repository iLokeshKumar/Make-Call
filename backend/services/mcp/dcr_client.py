"""
dcr_client.py - Dynamic Client Registration (RFC 7591) + OAuth 2.1 / PKCE helpers.

Used by MCP servers that implement OAuth 2.1 + DCR instead of pre-registered
client credentials (e.g. Cal.com, Calendly).

Typical flow
------------
1. discover_protected_resource(mcp_base_url)  → resource metadata
2. discover_auth_server(mcp_base_url)         → auth server metadata (endpoints)
3. register_client(registration_endpoint, ...)→ {client_id}  (store per company)
4. generate_pkce()                            → (code_verifier, code_challenge)
5. build_auth_url(...)                        → redirect URL for browser
6. exchange_code(...)                         → {access_token, refresh_token, ...}
7. refresh_access_token(...)                  → {access_token, ...}
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Optional
from urllib.parse import urlencode

import httpx


async def discover_protected_resource(mcp_base_url: str) -> dict:
    """GET <mcp_base_url>/.well-known/oauth-protected-resource"""
    url = mcp_base_url.rstrip("/") + "/.well-known/oauth-protected-resource"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def discover_auth_server(mcp_base_url: str) -> dict:
    """GET <mcp_base_url>/.well-known/oauth-authorization-server"""
    url = mcp_base_url.rstrip("/") + "/.well-known/oauth-authorization-server"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def register_client(
    registration_endpoint: str,
    client_name: str,
    redirect_uris: list[str],
) -> dict:
    """
    POST to registration_endpoint (DCR RFC 7591).
    Returns {client_id, ...} — no client_secret (public client).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            registration_endpoint,
            json={
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        resp.raise_for_status()
        return resp.json()


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge_s256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scopes: Optional[list[str]] = None,
) -> str:
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return authorization_endpoint + "?" + urlencode(params)


async def exchange_code(
    token_endpoint: str,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """POST to token_endpoint. Returns {access_token, refresh_token, expires_in, ...}"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
    client_id: str,
) -> dict:
    """Exchange a refresh token for a new access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()
