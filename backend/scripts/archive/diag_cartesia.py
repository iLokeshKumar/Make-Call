import asyncio
import os
import base64
from cartesia import AsyncCartesia
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("CARTESIA_API_KEY")
voice_id = os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")

async def test_cartesia():
    print(f"Testing Cartesia with Voice ID: {voice_id}")
    client = AsyncCartesia(api_key=api_key)
    
    try:
        async with client.tts.websocket_connect() as ws:
            tts_event = {
                "model_id": "sonic-3",
                "voice": {
                    "mode": "id",
                    "id": voice_id,
                },
                "transcript": "Hello, I am testing the Cartesia text to speech service. Can you hear me?",
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_mulaw",
                    "sample_rate": 8000,
                },
                "language": "en",
                "add_timestamps": False,
            }
            
            await ws.send(tts_event)
            
            audio_data = b""
            print("Receiving audio...")
            while True:
                try:
                    chunk = await asyncio.wait_for(ws.recv_bytes(), timeout=2.0)
                    if chunk:
                        audio_data += chunk
                        print(f"Received chunk: {len(chunk)} bytes")
                except asyncio.TimeoutError:
                    print("Timeout reached (expected at end of stream)")
                    break
            
            if len(audio_data) > 0:
                print(f"✅ Success! Total audio size: {len(audio_data)} bytes")
            else:
                print("❌ Failure: No audio data received.")
                
    except Exception as e:
        print(f"❌ Error during Cartesia test: {e}")

if __name__ == "__main__":
    asyncio.run(test_cartesia())
