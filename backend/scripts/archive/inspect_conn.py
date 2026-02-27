import cartesia
import inspect
import asyncio

async def inspect_connection():
    c = cartesia.AsyncCartesia(api_key='test')
    
    print("--- TTS WebSocket Connection Inspection ---")
    try:
        # We need to actually enter the context to get the connection object
        # but for inspection we can try to look at what the manager returns
        manager = c.tts.websocket_connect()
        # In 3.0.0, websocket_connect returns an AsyncTTSResourceConnectionManager
        # Let's try to find what it yields
        print("Manager type:", type(manager))
        
        # We'll try to instantiate the connection class directly or look at the type hint if possible
        # Or just run it and inspect in the context
        async with manager as ws:
            print("Connection object type:", type(ws))
            print("Connection methods:", [a for a in dir(ws) if not a.startswith('_')])
            if hasattr(ws, 'send'):
                print("Connection.send signature:", inspect.signature(ws.send))
            if hasattr(ws, 'receive'):
                print("Connection.receive signature:", inspect.signature(ws.receive))
    except Exception as e:
        print("Failed to inspect TTS connection:", e)

if __name__ == "__main__":
    asyncio.run(inspect_connection())
