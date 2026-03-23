import sys
import os
from sqlmodel import Session, text

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import engine

def check_columns():
    with Session(engine) as session:
        # Check user table columns
        result = session.exec(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user'")).all()
        columns = [r[0] for r in result]
        print(f"Columns in 'user' table: {columns}")
        
        has_name = 'company_name' in columns
        has_website = 'company_website' in columns
        
        print(f"Has company_name: {has_name}")
        print(f"Has company_website: {has_website}")

if __name__ == "__main__":
    check_columns()
