import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

print(f"Testing connection to: {DATABASE_URL}")
try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("✅ Successfully connected to PostgreSQL!")
except Exception as e:
    print(f"❌ Connection failed: {e}")
