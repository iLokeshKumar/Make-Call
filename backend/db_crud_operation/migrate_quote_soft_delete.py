import sys
import os
from sqlalchemy import text

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import engine


def migrate():
    print("Adding deleted_at column to quotes table...")
    with engine.connect() as conn:
        try:
            conn.execute(text(
                'ALTER TABLE quotes ADD COLUMN deleted_at TIMESTAMPTZ;'
            ))
            conn.commit()
            print("Column added successfully.")
        except Exception as e:
            if "already exists" in str(e):
                print("Column already exists, skipping.")
            else:
                raise e


if __name__ == "__main__":
    migrate()
