import sys
import os
from sqlmodel import Session, text

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine

def add_user_id_to_interaction():
    with Session(engine) as session:
        try:
            # Check if column exists
            result = session.exec(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'interaction' AND column_name = 'user_id'")).first()
            if not result:
                print("Adding 'user_id' column to 'interaction' table...")
                session.exec(text("ALTER TABLE interaction ADD COLUMN user_id INTEGER REFERENCES \"user\"(id)"))
                session.commit()
                print("Successfully added 'user_id' column.")
            else:
                print("'user_id' column already exists in 'interaction' table.")
        except Exception as e:
            print(f"Error: {e}")
            session.rollback()

if __name__ == "__main__":
    add_user_id_to_interaction()
