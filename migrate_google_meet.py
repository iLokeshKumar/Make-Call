"""
Migration: Add google_meet_link column to appointment table

Run this script to add the google_meet_link column if it doesn't exist
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)

def add_google_meet_link_column():
    """Add google_meet_link column to appointment table"""
    with engine.connect() as connection:
        try:
            # Check if column already exists
            check_query = text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name='appointment' AND column_name='google_meet_link'
            """)
            result = connection.execute(check_query).first()
            
            if result:
                print("✅ google_meet_link column already exists")
                return
            
            # Add the column
            alter_query = text("""
                ALTER TABLE appointment 
                ADD COLUMN google_meet_link VARCHAR(500) DEFAULT NULL
            """)
            connection.execute(alter_query)
            connection.commit()
            print("✅ Successfully added google_meet_link column to appointment table")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            connection.rollback()

if __name__ == "__main__":
    add_google_meet_link_column()
