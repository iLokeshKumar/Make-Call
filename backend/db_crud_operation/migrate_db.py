from sqlalchemy import create_engine, text
from database import DATABASE_URL

def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("Adding 'source' column to 'lead' table...")
        try:
            conn.execute(text("ALTER TABLE lead ADD COLUMN source VARCHAR"))
            conn.commit()
            print("Migration successful.")
        except Exception as e:
            print(f"Migration failed (maybe column exists?): {e}")

if __name__ == "__main__":
    migrate()
