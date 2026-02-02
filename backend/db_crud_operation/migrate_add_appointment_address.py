"""Idempotent migration to add address columns to appointment table
Adds: street_address (text), city, district, state, pincode
"""
from sqlalchemy import text
from sqlalchemy import create_engine
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)

def column_exists(conn, table_name, column_name):
    q = text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :col"
    )
    res = conn.execute(q, {"table": table_name, "col": column_name}).fetchone()
    return bool(res)


def add_columns():
    with engine.begin() as conn:
        cols = [
            ("street_address", "text"),
            ("city", "varchar(128)"),
            ("district", "varchar(128)"),
            ("state", "varchar(128)"),
            ("pincode", "varchar(32)"),
        ]
        for col, coltype in cols:
            if not column_exists(conn, "appointment", col):
                print(f"Adding column {col} to appointment")
                conn.execute(text(f"ALTER TABLE appointment ADD COLUMN {col} {coltype} DEFAULT NULL"))
            else:
                print(f"Column {col} already exists; skipping")

if __name__ == '__main__':
    add_columns()
    print("Migration complete.")
