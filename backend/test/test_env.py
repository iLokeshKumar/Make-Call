import os
from dotenv import load_dotenv

print("1. Before load_dotenv:", os.environ.get("CEREBRAS_MODEL"))
load_dotenv("backend/.env")
print("2. After default load_dotenv:", os.environ.get("CEREBRAS_MODEL"))
load_dotenv("backend/.env", override=True)
print("3. After load_dotenv(override=True):", os.environ.get("CEREBRAS_MODEL"))
