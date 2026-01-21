from sqlalchemy import create_engine, text
from database import DATABASE_URL, AuditMixin, Lead, Interaction, Product, SystemSettings

def migrate_audit():
    engine = create_engine(DATABASE_URL)
    tables = ['lead', 'interaction', 'product', 'systemsettings']
    columns = [
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("created_by", "VARCHAR DEFAULT 'System'"),
        ("updated_by", "VARCHAR")
    ]

    with engine.connect() as conn:
        for table in tables:
            print(f"Migrating table: {table}")
            for col_name, col_type in columns:
                try:
                    # Check if column exists first to avoid errors (or just try/except)
                    # For simplicity in this script, we'll try to add and catch error if it exists.
                    print(f"  Adding {col_name}...")
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                except Exception as e:
                    print(f"  Skipping {col_name} (might exist): {e}")
                    # If it exists, we might want to set default if null, but schema update is main goal.
            
            conn.commit()
    
    print("Audit migration complete.")

if __name__ == "__main__":
    migrate_audit()
