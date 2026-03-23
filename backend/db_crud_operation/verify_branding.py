import sys
import os
from sqlmodel import Session, text, select

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine, Interaction, User
from email_service import get_styled_html

def verify_db_schema():
    print("--- Verifying Database Schema ---")
    with Session(engine) as session:
        try:
            # Check interaction table for user_id
            result = session.exec(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'interaction' AND column_name = 'user_id'")).first()
            if result:
                print("SUCCESS: 'user_id' column exists in 'interaction' table.")
            else:
                print("FAILURE: 'user_id' column MISSING in 'interaction' table.")

            # Check user table for branding columns
            res_name = session.exec(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user' AND column_name = 'company_name'")).first()
            res_web = session.exec(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user' AND column_name = 'company_website'")).first()
            
            if res_name and res_web:
                 print("SUCCESS: Branding columns exist in 'user' table.")
            else:
                 print("FAILURE: Branding columns MISSING in 'user' table.")
        except Exception as e:
            print(f"Error checking DB: {e}")

def verify_html_logic():
    print("\n--- Verifying HTML Branding Logic ---")
    
    # Test Fallback
    html_fallback = get_styled_html("Test", "Body")
    if 'https://rio-crm.example.com/' in html_fallback and 'Rio CRM' in html_fallback:
        print("SUCCESS: Fallback branding confirmed.")
    else:
        print("FAILURE: Fallback branding failed.")

    # Test Clickability
    html_custom = get_styled_html("Test", "Body", company_name="MyCorp", company_website="https://mycorp.com")
    if '<a href="https://mycorp.com"' in html_custom and 'MyCorp</a>' in html_custom:
        print("SUCCESS: Clickable company link confirmed.")
    else:
        print("FAILURE: Clickable company link failed.")
        
    # Check Inline Styles (since we moved to inline for compatibility)
    if 'style="color: inherit; text-decoration: none;"' in html_custom:
        print("SUCCESS: Link styles confirmed in HTML tag.")
    else:
        print("FAILURE: Link styles missing from tag.")

if __name__ == "__main__":
    verify_db_schema()
    verify_html_logic()
