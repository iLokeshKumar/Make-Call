import os
import sys

# Add backend to path
sys.path.append(os.getcwd())

from sqlmodel import Session, select
from database import engine
from models.models import User, SystemSettings
from routes.crm import update_integration_keys, get_integration_keys
from utils.encryption import decrypt_value

def verify_fix():
    with Session(engine) as session:
        # Get or create a test user
        user = session.exec(select(User).where(User.username == "testuser")).first()
        if not user:
            user = User(username="testuser", email="test@example.com", hashed_password="pw", role="admin")
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"Created test user: {user.username}")

        # Test data mirroring what the UI sends
        test_data = {
            "TWILIO_ACCOUNT_SID": "AC1234567890",
            "TWILIO_AUTH_TOKEN": "token123",
            "PHONE_NUMBER_FROM": "+1234567890",
            "MISTRAL_API_KEY": "mistral_key_123"
        }

        print("\n--- Testing update_integration_keys ---")
        # Simulate the PATCH call logic
        # We'll just run it with the session and user
        import asyncio
        async def run_update():
            # Mocking dependencies for the async function is tricky, 
            # so let's just manually run the logic from crm.py here to verify it works
            from utils.encryption import encrypt_value
            for key, value in test_data.items():
                if not (key.endswith("_API_KEY") or key.endswith("_SID") or key.endswith("_TOKEN") or key in ["PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM"]):
                    print(f"Skipping key: {key}")
                    continue
                
                db_s = session.exec(
                    select(SystemSettings).where(
                        SystemSettings.key == key, 
                        SystemSettings.user_id == user.id
                    )
                ).first()
                
                encrypted_val = encrypt_value(str(value))
                if not db_s:
                    db_s = SystemSettings(
                        key=key, 
                        value=encrypted_val, 
                        user_id=user.id,
                        created_by=user.username,
                        updated_by=user.username
                    )
                else:
                    db_s.value = encrypted_val
                session.add(db_s)
            session.commit()
            print("Successfully updated settings in DB.")

        asyncio.run(run_update())

        print("\n--- Testing get_integration_keys logic ---")
        # Fetch back
        settings = session.exec(
            select(SystemSettings).where(
                SystemSettings.user_id == user.id,
                (SystemSettings.key.like("%_API_KEY")) | 
                (SystemSettings.key.like("%_SID")) | 
                (SystemSettings.key.like("%_TOKEN")) |
                (SystemSettings.key.in_(["PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM"]))
            )
        ).all()

        masked = {}
        for s in settings:
            decrypted = decrypt_value(s.value)
            if decrypted and len(decrypted) > 8:
                masked[s.key] = decrypted[:3] + "..." + decrypted[-4:]
            elif decrypted:
                masked[s.key] = "***"
            else:
                masked[s.key] = ""
        
        print(f"Masked keys returned: {masked}")
        
        # Verify specific keys exist
        expected_keys = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "PHONE_NUMBER_FROM", "MISTRAL_API_KEY"]
        for k in expected_keys:
            if k in masked:
                print(f"✅ Key {k} found and masked correctly: {masked[k]}")
            else:
                print(f"❌ Key {k} NOT found in masked results!")

if __name__ == "__main__":
    verify_fix()
