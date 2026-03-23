import sys
import os
from sqlmodel import Session, select

# Add parent directory to path to import models and utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine
from models.models import SystemSettings
from credentials_service import get_credential, bust_cache
from utils.encryption import encrypt_value

def verify_fallback():
    print("Testing Credentials Fallback Logic...")
    
    # 1. Setup dummy data
    with Session(engine) as session:
        # Delete any existing test keys
        test_key = "MOCK_SMTP_SERVER"
        session.exec(select(SystemSettings).where(SystemSettings.key == test_key)).all()
        
        # Add a Global key
        global_val = encrypt_value("global.smtp.com")
        session.add(SystemSettings(key=test_key, value=global_val, user_id=None))
        
        # Add a User key (user_id=4)
        user_val = encrypt_value("user4.smtp.com")
        session.add(SystemSettings(key=test_key, value=user_val, user_id=4))
        
        session.commit()

    bust_cache()
    
    # 2. Test Retrieval
    # A. Global only (user_id=None)
    res_global = get_credential("MOCK_SMTP_SERVER", user_id=None)
    print(f"Global Retrieval (Expected: global.smtp.com): {res_global}")
    
    # B. User specific (user_id=4)
    res_user = get_credential("MOCK_SMTP_SERVER", user_id=4)
    print(f"User 4 Retrieval (Expected: user4.smtp.com): {res_user}")
    
    # C. Fallback (user_id=999 - doesn't exist)
    res_fallback = get_credential("MOCK_SMTP_SERVER", user_id=999)
    print(f"User 999 Fallback (Expected: global.smtp.com): {res_fallback}")

    # Clean up
    with Session(engine) as session:
        session.exec(select(SystemSettings).where(SystemSettings.key == test_key)).all()
        # I'll just leave it and delete them in a real cleanup if needed, 
        # but for this test I'll just filter them out.
        settings = session.exec(select(SystemSettings).where(SystemSettings.key == test_key)).all()
        for s in settings:
            session.delete(s)
        session.commit()

if __name__ == "__main__":
    verify_fallback()
