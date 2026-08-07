import os
import json
import time
import base64
import httpx
from typing import Optional
from urllib.parse import urlencode
from . import storage

CLIENT_ID = os.getenv('LINKEDIN_CLIENT_ID')
CLIENT_SECRET = os.getenv('LINKEDIN_CLIENT_SECRET')
REDIRECT_URI = os.getenv('LINKEDIN_REDIRECT_URI')
API_BASE = os.getenv('LINKEDIN_API_BASE', 'https://api.linkedin.com')
TOKEN_URL = 'https://www.linkedin.com/oauth/v2/accessToken'


def build_auth_url(user_id: str, scope: str = 'r_liteprofile r_emailaddress') -> str:
    state = base64.urlsafe_b64encode(json.dumps({'user_id': user_id, 'ts': int(time.time())}).encode()).decode()
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': scope,
        'state': state
    }
    return f'https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}'


async def exchange_code_for_token(code: str) -> dict:
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(TOKEN_URL, data=data, headers={'Accept': 'application/json'})
        r.raise_for_status()
        return r.json()


async def refresh_token(refresh_token: str) -> dict:
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(TOKEN_URL, data=data, headers={'Accept': 'application/json'})
        r.raise_for_status()
        return r.json()


async def get_valid_access_token(user_id: str) -> Optional[str]:
    token_row = storage.get_token(user_id)
    if not token_row:
        return None
    now = int(time.time())
    expires_at = token_row.get('expires_at') or 0
    if expires_at and expires_at - 60 > now:
        return token_row['access_token']
    # try to refresh
    refresh = token_row.get('refresh_token')
    if not refresh:
        return token_row['access_token']  # maybe non-expiring token
    new = await refresh_token(refresh)
    access = new.get('access_token')
    refresh_new = new.get('refresh_token', refresh)
    expires_in = new.get('expires_in')
    expires_at_new = int(time.time()) + int(expires_in) if expires_in else None
    storage.save_token(user_id, access, refresh_new, expires_at_new, token_row.get('scope'))
    return access


async def proxy_linkedin_request(method: str, path: str, access_token: str, params: dict = None, json_body: dict = None, headers: dict = None):
    url = f"{API_BASE}{path}"
    async with httpx.AsyncClient() as client:
        req_headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}
        if headers:
            req_headers.update(headers)
        r = await client.request(method.upper(), url, params=params, json=json_body, headers=req_headers, timeout=30.0)
        r.raise_for_status()
        return r.json()
