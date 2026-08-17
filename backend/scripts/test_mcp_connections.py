"""
test_mcp_connections.py - Test external MCP + REST connections from Rio.

Run from backend/:
  python scripts/test_mcp_connections.py
"""
import asyncio
import json
import os
import sys

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

import httpx

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_MCP_URL = "https://mcp.apollo.io/mcp"
APOLLO_REST_URL = "https://api.apollo.io/v1"

SEP = "-" * 60


# ── 1. Apollo REST API ─────────────────────────────────────────────────────── #

async def test_apollo_rest():
    print(f"\n{SEP}")
    print("TEST 1: Apollo REST API (uses API key directly)")
    print(SEP)
    if not APOLLO_API_KEY:
        print("  SKIP — APOLLO_API_KEY not set")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{APOLLO_REST_URL}/mixed_people/search",
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Api-Key": APOLLO_API_KEY,
                },
                json={"q_keywords": "CTO fintech", "page": 1, "per_page": 3},
            )
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get("people", [])
                print(f"  OK — Apollo REST connected. Found {len(contacts)} sample contacts.")
                for c in contacts[:2]:
                    print(f"    • {c.get('name')} — {c.get('title')} @ {c.get('organization_name')}")
                return True
            else:
                print(f"  FAIL — HTTP {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        print(f"  ERROR — {e}")
        return False


# ── 2. Apollo MCP (OAuth Bearer attempt) ─────────────────────────────────────#

async def test_apollo_mcp_with_api_key():
    print(f"\n{SEP}")
    print("TEST 2: Apollo MCP server (API key as Bearer token)")
    print(SEP)
    if not APOLLO_API_KEY:
        print("  SKIP — APOLLO_API_KEY not set")
        return False

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "rio-crm", "version": "1.0"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                APOLLO_MCP_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {APOLLO_API_KEY}",
                },
            )
            print(f"  HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  OK — MCP initialize succeeded: {json.dumps(data, indent=2)[:300]}")
                # Try listing tools
                tools_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                resp2 = await client.post(
                    APOLLO_MCP_URL,
                    json=tools_payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {APOLLO_API_KEY}",
                    },
                )
                if resp2.status_code == 200:
                    tools = resp2.json().get("result", {}).get("tools", [])
                    print(f"  Tools available: {len(tools)}")
                    for t in tools[:5]:
                        print(f"    • {t.get('name')}")
                return True
            elif resp.status_code in (401, 403):
                print("  FAIL — API key rejected. Apollo MCP requires OAuth (not API key).")
                print("  -> Use Apollo REST API instead (Test 1 above works fine).")
                return False
            else:
                print(f"  FAIL — {resp.text[:300]}")
                return False
    except Exception as e:
        print(f"  ERROR — {e}")
        return False


# ── 3. Apollo MCP OAuth metadata ─────────────────────────────────────────────#

async def test_apollo_mcp_oauth_info():
    print(f"\n{SEP}")
    print("TEST 3: Apollo MCP OAuth server metadata")
    print(SEP)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://mcp.apollo.io/.well-known/oauth-authorization-server")
            if resp.status_code == 200:
                meta = resp.json()
                print("  Apollo MCP uses OAuth 2.0:")
                print(f"    Auth endpoint:  {meta.get('authorization_endpoint')}")
                print(f"    Token endpoint: {meta.get('token_endpoint')}")
                print(f"    Scopes:         {meta.get('scopes_supported', [])}")
                print()
                print("  To connect Rio to Apollo MCP properly:")
                print("  1. Register Rio as an OAuth client at Apollo")
                print("  2. Complete OAuth flow to get access_token")
                print("  3. Store token and use it in mcp_client.py headers")
                print()
                print("  OR: Use Apollo REST API (Test 1) — same data, API key works directly.")
            else:
                print(f"  HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ERROR — {e}")


# ── 4. Zoho — no public MCP ──────────────────────────────────────────────────#

def explain_zoho():
    print(f"\n{SEP}")
    print("ZOHO MCP — Status")
    print(SEP)
    print("  Zoho does NOT have a public standalone MCP server.")
    print("  The Zoho tools in claude.ai are Anthropic-hosted — not self-connectable.")
    print()
    print("  Your options for Zoho in Rio:")
    print("  A) Zoho REST API directly (recommended)")
    print("     -> ZOHO_CRM_ACCESS_TOKEN + ZOHO_ORG_ID in .env")
    print("     -> POST https://www.zohoapis.com/crm/v2/Leads")
    print()
    print("  B) Zoho Catalyst / Zoho Flow webhooks")
    print("     -> Rio emits webhook events -> Zoho Flow picks them up")
    print()
    print("  C) Make.com or Zapier as a bridge")
    print("     -> Rio webhook -> Make -> Zoho CRM module")
    print(SEP)


# ── Main ──────────────────────────────────────────────────────────────────────#

async def main():
    print("\n=== Rio MCP Connection Tests ===")

    rest_ok = await test_apollo_rest()
    mcp_ok  = await test_apollo_mcp_with_api_key()

    if not mcp_ok:
        await test_apollo_mcp_oauth_info()

    explain_zoho()

    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)
    print(f"  Apollo REST API:  {'OK working' if rest_ok else 'FAIL failed'}")
    print(f"  Apollo MCP:       {'OK working' if mcp_ok else 'WARN needs OAuth (use REST instead)'}")
    print(f"  Zoho MCP:         N/A not available (use REST API or webhook bridge)")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
