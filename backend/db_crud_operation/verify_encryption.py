import sys
import os
from sqlmodel import Session, select

# Add parent directory to path to import models and utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine
from models.models import User
from utils.encryption import decrypt_value

def verify():
    print("Verifying User PII Encryption (Email & Phone)...")
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == 'lokesh')).first()
        if user:
            print(f"User: {user.username}")
            
            print(f"Email (Raw): {user.email[:20]}...")
            print(f"Email Hash: {user.email_hash[:10]}...")
            print(f"Decrypted Email: {decrypt_value(user.email)}")
            
            print(f"Phone (Raw): {user.phone_number[:20]}...")
            print(f"Phone Hash: {user.phone_number_hash[:10]}...")
            print(f"Decrypted Phone: {decrypt_value(user.phone_number)}")
        else:
            print("User 'lokesh' not found.")

if __name__ == "__main__":
    verify()
