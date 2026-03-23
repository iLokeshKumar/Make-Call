import sys
import os
from sqlalchemy import text

# Add parent directory to path to import models and utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine

def add_column():
    print("Adding email_hash column to user table...")
    with engine.connect() as conn:
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN email_hash VARCHAR;'))
            conn.execute(text('CREATE INDEX idx_user_email_hash ON "user" (email_hash);'))
            conn.commit()
            print("Column and index added successfully.")
        except Exception as e:
            print(f"Error: {e}")
            if "already exists" in str(e):
                print("Column already exists, proceeding...")
            else:
                raise e

if __name__ == "__main__":
    add_column()
