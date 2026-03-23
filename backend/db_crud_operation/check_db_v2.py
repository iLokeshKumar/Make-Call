import sqlite3
import os

# Try common locations
paths = [
    os.path.join(os.getcwd(), 'backend', 'crm.db'),
    os.path.join(os.getcwd(), 'crm.db'),
]

for db_path in paths:
    if os.path.exists(db_path):
        print(f"--- Checking DB at {db_path} ---")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            print(f"Tables: {[t[0] for t in tables]}")
            
            # If systemsettings exists, check it
            if any('systemsettings' in t[0].lower() for t in tables):
                table_name = [t[0] for t in tables if 'systemsettings' in t[0].lower()][0]
                print(f"Inspecting {table_name}...")
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                print(f"Row count: {cursor.fetchone()[0]}")
                cursor.execute(f"SELECT key, user_id FROM {table_name} LIMIT 10")
                for row in cursor.fetchall():
                    print(f"Key: {row[0]}, UserID: {row[1]}")
            
            conn.close()
        except Exception as e:
            print(f"Error: {e}")
    else:
        print(f"DB not found at {db_path}")
