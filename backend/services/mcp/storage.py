import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict

DB = Path(__file__).parent / 'mcp_linkedin.db'

def _conn():
    return sqlite3.connect(DB, check_same_thread=False)

def save_token(user_id: str, access_token: str, refresh_token: Optional[str], expires_at: Optional[int], scope: Optional[str]):
    conn = _conn()
    c = conn.cursor()
    now = int(time.time())
    c.execute('''INSERT OR REPLACE INTO tokens (user_id, access_token, refresh_token, expires_at, scope, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, access_token, refresh_token, expires_at, scope, now))
    conn.commit()
    conn.close()

def get_token(user_id: str) -> Optional[Dict]:
    conn = _conn()
    c = conn.cursor()
    c.execute('SELECT access_token, refresh_token, expires_at, scope, created_at FROM tokens WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'access_token': row[0],
        'refresh_token': row[1],
        'expires_at': row[2],
        'scope': row[3],
        'created_at': row[4]
    }

def delete_token(user_id: str):
    conn = _conn()
    c = conn.cursor()
    c.execute('DELETE FROM tokens WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
