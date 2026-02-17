import os
from dotenv import load_dotenv
from deepgram import DeepgramClient

load_dotenv("backend/.env")
api_key = os.getenv("DEEPGRAM_API_KEY")
print(f"DEEPGRAM_API_KEY found: {bool(api_key)}")
if api_key:
    print(f"Key starts with: {api_key[:4]}...")
else:
    print("❌ Key NOT found in environment variables.")

try:
    # Pass explicitly if env var fails for some reason
    client = DeepgramClient(api_key=api_key)
    print("Client initialized")
    
    if hasattr(client, 'listen'):
        print("client.listen found")
        if hasattr(client.listen, 'v1'):
             print("client.listen.v1 found")
             if hasattr(client.listen.v1, 'connect'):
                 print("client.listen.v1.connect found")
             else:
                 print("client.listen.v1.connect NOT found")
                 print(dir(client.listen.v1))
        else:
             print("client.listen.v1 NOT found")
             print(dir(client.listen))
             
             # Maybe it's live?
             if hasattr(client.listen, 'live'):
                 print("client.listen.live found")
                 if hasattr(client.listen.live, 'v1'):
                     print("client.listen.live.v1 found")
    else:
        print("client.listen NOT found")
        print(dir(client))

except Exception as e:
    print(f"Error: {e}")
