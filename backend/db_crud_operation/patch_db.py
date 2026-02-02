from sqlmodel import Session, text
from database import engine

def patch_database():
    print("Patching database schema...")
    with Session(engine) as session:
        try:
            # Add email_verified column
            session.exec(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;'))
            # Add verification_token column
            session.exec(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS verification_token VARCHAR;'))
            session.commit()
            print("Successfully added email_verified and verification_token columns to the 'user' table.")
        except Exception as e:
            print(f"Error patching database: {e}")
            session.rollback()

if __name__ == "__main__":
    patch_database()
