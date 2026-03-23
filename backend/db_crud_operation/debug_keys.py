import os
import sys
from dotenv import load_dotenv

# Add the parent 'backend' directory to sys.path so we can import 'models' and 'utils'
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if backend_path not in sys.path:
    sys.path.append(backend_path)

# Load .env from backend directory BEFORE other imports
env_path = os.path.join(backend_path, '.env')
load_dotenv(env_path)

from sqlmodel import Session, select, create_engine
from models.models import SystemSettings, User
from utils.encryption import decrypt_value

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or not DATABASE_URL.startswith("postgresql"):
    DATABASE_URL = "postgresql://postgres:1234@localhost/calls"

engine = create_engine(DATABASE_URL)

def check_settings():
    with Session(engine) as session:
        print("--- All SystemSettings for User 4 ---")
        stmt = select(SystemSettings).where(SystemSettings.user_id == 4)
        settings = session.exec(stmt).all()
        for s in settings:
            try:
                # Decide if we should try to decrypt
                should_decrypt = (
                    s.key.endswith("_API_KEY") or 
                    s.key.endswith("_TOKEN") or 
                    s.key.endswith("_SID") or 
                    s.key.startswith("SMTP_") or 
                    "VOICE" in s.key or 
                    "MODEL" in s.key
                )
                decrypted = decrypt_value(s.value) if should_decrypt else s.value
                masked = decrypted[:10] + "..." + decrypted[-4:] if decrypted and len(decrypted) > 15 else decrypted
                print(f"ID: {s.id} | Key: {s.key} | Value: '{masked}'")
            except Exception as e:
                print(f"ID: {s.id} | Key: {s.key} | Value: [DECRYPTION FAILED: {e}]")

        print("\n--- User IDs ---")
        users = session.exec(select(User)).all()
        for u in users:
            print(f"ID: {u.id} | Username: {u.username}")

if __name__ == "__main__":
    check_settings()
