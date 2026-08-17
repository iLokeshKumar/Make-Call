import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select
from models.models import Product
from rag_service import sync_products_to_chroma
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def sync():
    with SessionLocal() as session:
        products = session.execute(select(Product)).scalars().all()
        print(f"Found {len(products)} products in Postgres.")
        sync_products_to_chroma(products)
        print("Sync finished.")

if __name__ == "__main__":
    sync()
