import cartesia
import inspect
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def inspect_connection():
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        print("CARTESIA_API_KEY not found in .env")
        return
        
    c = cartesia.AsyncCartesia(api_key=api_key)
    
    print("--- TTS WebSocket Connection Inspection ---")
    try:
        async with c.tts.websocket_connect() as ws:
            print("Connection object type:", type(ws))
            print("Connection.send signature:", inspect.signature(ws.send))
            # Test a minimal send to see if it works without model_id in send()
            # No, wait, if I don't send anything it might just hang.
            # I just need the signature for now.
    except Exception as e:
        print("Failed to inspect TTS connection:", e)

if __name__ == "__main__":
    asyncio.run(inspect_connection())
