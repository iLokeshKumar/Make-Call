import sqlite3
import os

db_path = os.path.join(os.getcwd(), 'backend', 'crm.db')
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT key, value, user_id FROM systemsettings WHERE key = 'CARTESIA_API_KEY';")
rows = cursor.fetchall()
for row in rows:
    print(f"Key: {row[0]}, Value: {row[1][:10]}...{row[1][-10:] if len(row[1]) > 10 else ''}, UserID: {row[2]}")
conn.close()
