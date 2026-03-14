import os
import sys
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from models.models import User
from google_calendar_service import GoogleMeetGenerator
from dotenv import load_dotenv
import logging

# Setup logging to see the refresh process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load local environment variables
load_dotenv()

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_refresh():
    with SessionLocal() as session:
        # 1. Fetch the user (assuming the primary user has the token)
        # We'll just take the first user that has a refresh token
        user = session.execute(select(User).where(User.google_refresh_token != None)).scalars().first()
        
        if not user:
            print("❌ No user found with Google Refresh Token in database.")
            return

        print(f"Testing refresh for user: {user.username}")
        print(f"Current Expiry in DB: {user.google_token_expiry}")
        old_token = user.google_access_token
        
        # 2. Initialize Generator with User and Session
        generator = GoogleMeetGenerator(user=user, session=session)
        
        # 3. Force a refresh check
        print("Triggering calendar service (should trigger refresh if expired)...")
        try:
            # This internal call triggers _get_calendar_service which has our refresh logic
            service = generator._get_calendar_service()
            print("Calendar service obtained.")
            
            # 4. Check if token changed and was saved
            session.refresh(user)
            print(f"New Expiry in DB: {user.google_token_expiry}")
            
            if user.google_access_token != old_token:
                print("SUCCESS: Access token was refreshed and PERSISTED to the database!")
            else:
                print("Token was not changed (possibly not expired yet or refresh not needed).")
                
                # Let's check if it's actually expired according to the credentials object
                if generator.credentials.expired:
                    print("Credentials reported as expired but token didn't change? Check logs.")
                else:
                    print("Credentials are currently valid.")

        except Exception as e:
            print(f"Error during refresh test: {e}")

if __name__ == "__main__":
    test_refresh()
