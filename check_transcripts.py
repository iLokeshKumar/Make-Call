from sqlmodel import Session, create_engine, select
from database import Interaction
import os

DATABASE_URL = "sqlite:///./crm.db"
engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    interactions = session.exec(select(Interaction).order_by(Interaction.timestamp.desc()).limit(10)).all()
    print(f"Found {len(interactions)} interactions:")
    for i in interactions:
        print(f"ID: {i.id}, Lead ID: {i.lead_id}, Type: {i.type}, Content: {i.content}")
        print(f"Transcript Snippet: {repr(i.transcript[:100]) if i.transcript else 'NONE'}")
        print("-" * 20)