import sys
import os
from sqlmodel import Session, select

# Add parent directory to path to import models and utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine
from models.models import User
from utils.encryption import encrypt_value, decrypt_value, generate_blind_index

def migrate_users():
    print("Starting full user PII migration (Email & Phone)...")
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        migrated_count = 0
        
        for user in users:
            updated = False
            
            # 1. Migrate Email
            if user.email and not user.email.startswith('gAAAAA'):
                print(f"Encrypting email for user: {user.username}")
                plain_email = user.email
                user.email = encrypt_value(plain_email)
                user.email_hash = generate_blind_index(plain_email)
                updated = True
            elif user.email and not user.email_hash:
                plain_email = decrypt_value(user.email)
                if plain_email:
                    user.email_hash = generate_blind_index(plain_email)
                    updated = True

            # 2. Migrate Phone Number
            if user.phone_number and not user.phone_number.startswith('gAAAAA'):
                print(f"Encrypting phone_number for user: {user.username}")
                plain_phone = user.phone_number
                user.phone_number = encrypt_value(plain_phone)
                user.phone_number_hash = generate_blind_index(plain_phone)
                updated = True
            elif user.phone_number and not user.phone_number_hash:
                plain_phone = decrypt_value(user.phone_number)
                if plain_phone:
                    user.phone_number_hash = generate_blind_index(plain_phone)
                    updated = True

            if updated:
                session.add(user)
                migrated_count += 1

        session.commit()
        print(f"Migration complete. Total users updated: {migrated_count}")

if __name__ == "__main__":
    migrate_users()
