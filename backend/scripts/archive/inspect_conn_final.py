import cartesia
import inspect
import asyncio

async def inspect_connection():
    api_key = "sk_car_o4Qx6nbnMeL3Cu8WbDEMni"
    c = cartesia.AsyncCartesia(api_key=api_key)
    
    print("--- TTS WebSocket Connection Inspection ---")
    try:
        async with c.tts.websocket_connect() as ws:
            print("Connection object type:", type(ws))
            print("Connection methods:", [a for a in dir(ws) if not a.startswith('_')])
            if hasattr(ws, 'send'):
                print("Connection.send signature:", inspect.signature(ws.send))
    except Exception as e:
        print("Failed to inspect TTS connection:", e)

if __name__ == "__main__":
    asyncio.run(inspect_connection())
