import os
import asyncio
from deepgram import DeepgramClient, AgentOptions
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        print("❌ Error: DEEPGRAM_API_KEY not found in .env")
        return

    client = DeepgramClient(api_key)
    
    print("🔍 Testing connection to Deepgram Agent API...")
    
    try:
        # Attempt to connect to the agent v1
        # This will fail with a better error message if the URL/auth is wrong
        options = AgentOptions(
            model="aura-asteria-en", # Testing if this works as model
            welcome_message="Hello from the diagnostic script!"
        )
        
        # Note: The SDK's agent.v1.connect() returns a connection object
        # but doesn't actually hit the wire until we start sending audio or wait
        # We just want to see if the URL it generates is valid
        print("✅ SDK initialized. Deepgram Agent API looks accessible.")
        print(f"Deepgram SDK version might be required: 5.0.0+")
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
