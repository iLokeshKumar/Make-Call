from sqlmodel import Session, create_engine, select
from database import Interaction
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    interactions = session.exec(select(Interaction).order_by(Interaction.timestamp.desc()).limit(10)).all()
    print(f"Latest 10 Interactions:")
    for i in interactions:
        print(f"ID: {i.id}, Lead ID: {i.lead_id}, Type: {i.type}, Content: {i.content}")
        print(f"Transcript: {repr(i.transcript) if i.transcript else 'NONE'}")
        print("-" * 20)
