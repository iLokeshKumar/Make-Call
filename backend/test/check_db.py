from sqlmodel import create_engine, Session, select
from backend.models.models import SystemSettings
import os
from dotenv import load_dotenv

load_dotenv("backend/.env")

engine = create_engine(os.getenv("DATABASE_URL"))
session = Session(engine)

result = session.exec(select(SystemSettings).where(SystemSettings.key.in_(["llm_provider", "llm_model"]))).all()

print("\n--- ACTIVE DATABASE SETTINGS ---")
for r in result:
    print(f"{r.key} = {r.value}")
print("--------------------------------\n")
