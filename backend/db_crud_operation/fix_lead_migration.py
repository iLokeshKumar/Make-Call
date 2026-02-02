from sqlalchemy import create_engine, text
from database import DATABASE_URL

def fix_lead_migration():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("Fixing 'lead' table migration...")
        columns = [
            ("created_by", "VARCHAR DEFAULT 'System'"),
            ("updated_by", "VARCHAR"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            # created_at already existed in Lead
        ]
        
        for col_name, col_type in columns:
            try:
                print(f"  Attempting to add {col_name} to lead...")
                conn.execute(text(f"ALTER TABLE lead ADD COLUMN {col_name} {col_type}"))
                conn.commit() # Commit after each success
                print(f"  Success: {col_name} added.")
            except Exception as e:
                print(f"  Skipped {col_name}: {e}")
                conn.rollback() # Important: Rollback if one fails so we can try next

        print("Lead table fix complete.")

if __name__ == "__main__":
    fix_lead_migration()
