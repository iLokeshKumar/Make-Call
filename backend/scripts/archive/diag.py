import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)

def check_extension():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector';"))
            ext = result.first()
            if ext:
                print(f"✅ 'vector' extension found: {ext[0]}")
            else:
                print("❌ 'vector' extension NOT found.")
    except Exception as e:
        print(f"Error checking extension: {e}")

def list_products():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id, name, price, stock FROM product;"))
            print("\n--- PRODUCTS ---")
            for row in result:
                print(row._mapping)
    except Exception as e:
        print(f"Error listing products: {e}")

if __name__ == "__main__":
    check_extension()
    list_products()
