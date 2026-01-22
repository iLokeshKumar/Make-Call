from sqlalchemy import create_engine, text
from database import DATABASE_URL

def migrate_enrichment():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("Adding 'enrichment_status' to 'lead' table...")
        try:
            conn.execute(text("ALTER TABLE lead ADD COLUMN enrichment_status VARCHAR DEFAULT 'Not Enriched'"))
            conn.commit()
            print("Success.")
        except Exception as e:
            print(f"Skipped: {e}")
            conn.rollback()

if __name__ == "__main__":
    migrate_enrichment()
