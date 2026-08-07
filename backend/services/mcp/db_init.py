import sqlite3
from pathlib import Path

DB = Path(__file__).parent / 'mcp_linkedin.db'

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS tokens (
        user_id TEXT PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT,
        expires_at INTEGER,
        scope TEXT,
        created_at INTEGER
    )
    ''')
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print('DB initialized at', DB)
