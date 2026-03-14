import os
import asyncio
import json
import aiohttp
from dotenv import load_dotenv

load_dotenv("backend/.env")
api_key = os.environ.get("Cerebras_API_Key")
model = "gpt-oss-120b"

async def test_cerebras():
    print(f"Testing Cerebras API with model {model}...")
    url = "https://api.cerebras.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello, which model are you?"}],
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            print("Status:", resp.status)
            print("Response:", text)

if __name__ == "__main__":
    asyncio.run(test_cerebras())
