import os
import time
import json
import base64
from fastapi import FastAPI, Request, HTTPException, Header, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
import asyncio
from . import linkedin, storage, db_init, auth
import httpx

app = FastAPI(title='Rio MCP LinkedIn Wrapper')

# initialize DB
try:
    db_init.init_db()
except Exception as e:
    print('DB init error', e)

RIO_API_KEY = os.getenv('RIO_API_KEY')
RIO_WEBHOOK_URL = os.getenv('RIO_WEBHOOK_URL')

class ProxyRequest(BaseModel):
    user_id: str
    method: str = 'GET'
    path: str
    params: dict = None
    json: dict = None
    headers: dict = None

@app.get('/health')
async def health():
    return {'status': 'ok', 'ts': int(time.time())}

@app.get('/oauth/start')
async def oauth_start(user_id: str, scope: str = 'r_liteprofile r_emailaddress'):
    if not linkedin.CLIENT_ID or not linkedin.CLIENT_SECRET or not linkedin.REDIRECT_URI:
        raise HTTPException(status_code=500, detail='LinkedIn client not configured')
    url = linkedin.build_auth_url(user_id, scope=scope)
    return RedirectResponse(url)

@app.get('/oauth/callback')
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f'Error from LinkedIn: {error}')
    if not code or not state:
        raise HTTPException(status_code=400, detail='Missing code/state')
    # decode state
    try:
        decoded = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        user_id = decoded.get('user_id')
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid state')
    token_data = await linkedin.exchange_code_for_token(code)
    access = token_data.get('access_token')
    refresh = token_data.get('refresh_token')
    expires_in = token_data.get('expires_in')
    expires_at = int(time.time()) + int(expires_in) if expires_in else None
    scope = token_data.get('scope')
    storage.save_token(user_id, access, refresh, expires_at, scope)
    # Optionally notify Rio via webhook
    if RIO_WEBHOOK_URL:
        asyncio.create_task(notify_rio_connected(user_id))
    return JSONResponse({'status': 'connected', 'user_id': user_id})

async def notify_rio_connected(user_id: str):
    async with asyncio.Semaphore(1):
        try:
            await httpx.post(RIO_WEBHOOK_URL, json={'event': 'linkedin.connected', 'user_id': user_id}, timeout=10.0)
        except Exception:
            pass

@app.post('/linkedin/request')
async def linkedin_request(req: ProxyRequest, x_rio_secret: str = Header(None), authorization: str = Header(None, alias='Authorization')):
    # authenticate via shared secret header or JWT
    auth.verify_api_call(x_rio_secret, authorization)
    token = await linkedin.get_valid_access_token(req.user_id)
    if not token:
        raise HTTPException(status_code=404, detail='No token for user_id; start OAuth flow')
    try:
        res = await linkedin.proxy_linkedin_request(req.method, req.path, token, params=req.params or {}, json_body=req.json, headers=req.headers)
        return JSONResponse(res)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

@app.post('/token/refresh')
async def token_refresh(user_id: str, x_rio_secret: str = Header(None), authorization: str = Header(None, alias='Authorization')):
    auth.verify_api_call(x_rio_secret, authorization)
    row = storage.get_token(user_id)
    if not row or not row.get('refresh_token'):
        raise HTTPException(status_code=404, detail='No refresh token available')
    new = await linkedin.refresh_token(row['refresh_token'])
    access = new.get('access_token')
    refresh = new.get('refresh_token', row['refresh_token'])
    expires_in = new.get('expires_in')
    expires_at = int(time.time()) + int(expires_in) if expires_in else None
    storage.save_token(user_id, access, refresh, expires_at, row.get('scope'))
    return {'status': 'refreshed', 'user_id': user_id}

@app.post('/unlink')
async def unlink(user_id: str, x_rio_secret: str = Header(None), authorization: str = Header(None, alias='Authorization')):
    auth.verify_api_call(x_rio_secret, authorization)
    storage.delete_token(user_id)
    return {'status': 'deleted', 'user_id': user_id}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('mcp.app:app', host=os.getenv('APP_HOST', '0.0.0.0'), port=int(os.getenv('APP_PORT', '8000')), reload=True)
