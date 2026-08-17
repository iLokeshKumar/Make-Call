import requests
import base64
import os
import asyncio
import websockets
from dotenv import load_dotenv

load_dotenv("backend/.env")

# Get credentials
EXOTEL_ACCOUNT_SID = os.getenv("EXOTEL_ACCOUNT_SID")
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN")
EXOPHONE = os.getenv("EXOPHONE")

print("=" * 60)
print("EXOTEL SIMPLE TEST")
print("=" * 60)
print(f"Account SID: {EXOTEL_ACCOUNT_SID}")
print(f"API Key: {EXOTEL_API_KEY[:10]}...")
print(f"Exophone: {EXOPHONE}")
print("=" * 60)

def _run_simple_test():
    # Test 1: Simple "Say" ExoML (no WebSocket)
    print("\n📞 TEST 1: Simple Call with 'Say' (no WebSocket)")
    print("-" * 60)

    try:
        customer_number = input("Enter customer number to call (e.g., 918148749703): ").strip()
    except Exception:
        customer_number = None

    if not customer_number:
        print("No customer number provided; skipping interactive Exotel test.")
        return

    exophone_number = EXOPHONE.replace("+", "")

    # Create simple ExoML that just says hello
    simple_exoml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Hello! This is a test call from Rio CRM. If you can hear this, your Exophone is working correctly.</Say>
    </Response>"""

    exoml_b64 = base64.b64encode(simple_exoml.encode()).decode()
    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_ACCOUNT_SID}/Calls/connect.json"
    applet_url = f"https://my.exotel.com/{EXOTEL_ACCOUNT_SID}/exoml/start_voice?exoml={exoml_b64}"

    data = {
        "From": customer_number,
        "CallerId": exophone_number,
        "CallType": "trans",
        "Url": applet_url,
        "TimeLimit": "120",
        "TimeOut": "30"
    }

    print(f"\n🔍 Request Details:")
    print(f"   URL: {url}")
    print(f"   From (Customer): {customer_number}")
    print(f"   CallerId (Exophone): {exophone_number}")
    print(f"   ExoML: {simple_exoml[:100]}...")

    auth = (EXOTEL_API_KEY, EXOTEL_API_TOKEN)

    try:
        response = requests.post(url, auth=auth, data=data)
        result = response.json()

        print(f"\n📡 Response:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Body: {result}")

        if response.status_code in [200, 201]:
            call_sid = result.get("Call", {}).get("Sid")
            print(f"\n✅ SUCCESS! Call initiated.")
            print(f"   Call SID: {call_sid}")
            print(f"\n   What happens next:")
            print(f"   1. Exotel calls {customer_number}")
            print(f"   2. Customer sees {exophone_number} on their phone")
            print(f"   3. When they answer, they hear: 'Hello! This is a test call...'")
        else:
            error = result.get("RestException", {})
            error_code = error.get("Code")
            error_msg = error.get("Message")

            print(f"\n❌ FAILED!")
            print(f"   Error Code: {error_code}")
            print(f"   Error Message: {error_msg}")

            if error_code == 34001:
                print(f"\n💡 Troubleshooting Error 34001:")
                print(f"   1. Check if Exophone {exophone_number} is verified:")
                print(f"      → Login to https://my.exotel.com")
                print(f"      → Go to 'Phone Numbers'")
                print(f"      → Look for {exophone_number}")
                print(f"      → Status should be 'Active' or 'Verified'")
                print(f"\n   2. If Exophone is NOT listed:")
                print(f"      → You need to purchase/add it first")
                print(f"      → Contact Exotel support")
                print(f"\n   3. Check number format:")
                print(f"      → Customer: {customer_number} (should be 91XXXXXXXXXX)")
                print(f"      → Exophone: {exophone_number} (should be 91XXXXXXXXXX)")
            elif error_code == 34010:
                print(f"\n💡 Troubleshooting Error 34010:")
                print(f"   → API credentials don't match Account SID")
                print(f"   → Check your .env file")
                print(f"   → Verify credentials in Exotel dashboard")

    except Exception as e:
        print(f"\n❌ Exception: {e}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    _run_simple_test()