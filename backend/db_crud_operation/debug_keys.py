import os
import sys
from sqlmodel import Session, select, create_engine
from models.models import SystemSettings, User
from utils.encryption import decrypt_value
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")
engine = create_engine(DATABASE_URL)

def check_settings():
    with Session(engine) as session:
        print("--- All SystemSettings for User 4 ---")
        stmt = select(SystemSettings).where(SystemSettings.user_id == 4)
        settings = session.exec(stmt).all()
        for s in settings:
            try:
                # FIX: Check s.key, not s itself
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
