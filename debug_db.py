from sqlmodel import Session, create_engine, text, select
from database import Lead, Interaction, Product, SystemSettings
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    # Check tables
    try:
        res = session.exec(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")).all()
        print(f"Tables in DB: {[r[0] for r in res]}")
    except Exception as e:
        print(f"Error checking tables: {e}")

    # Check lead count
    leads = session.exec(select(Lead)).all()
    print(f"Total Leads: {len(leads)}")

    # Check interaction count
    interactions = session.exec(select(Interaction)).all()
    print(f"Total Interactions: {len(interactions)}")
    for i in interactions[:5]:
        print(f"Interaction ID: {i.id}, Transcript Length: {len(i.transcript) if i.transcript else 0}")
