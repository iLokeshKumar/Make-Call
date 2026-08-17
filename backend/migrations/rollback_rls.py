#!/usr/bin/env python3
"""
Rollback RLS — drops tenant_isolation policies and disables RLS.

Usage
-----
python migrations/rollback_rls.py --table leads
python migrations/rollback_rls.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

import psycopg2

from migrations.apply_rls import ALL_TENANT_TABLES, POLICY_NAME, _connect, table_exists, policy_exists


def disable_rls_on_table(cur, table: str) -> None:
    if not table_exists(cur, table):
        print(f"  SKIP  {table!r} — does not exist")
        return
    if policy_exists(cur, table, POLICY_NAME):
        cur.execute(f'DROP POLICY "{POLICY_NAME}" ON "{table}"')
        print(f"  DROP POLICY  {table}.{POLICY_NAME}")
    cur.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    print(f"  DISABLE RLS  {table}")


def rollback_rls(tables: list[str]) -> None:
    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        print(f"\nRolling back RLS on {len(tables)} table(s)...\n")
        for table in tables:
            disable_rls_on_table(cur, table)
        conn.commit()
        print(f"\nDone.")
    except Exception as exc:
        conn.rollback()
        print(f"\nERROR — rolled back: {exc}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback Postgres RLS on tenant tables")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--table", metavar="NAME")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()

    tables = [args.table] if args.table else ALL_TENANT_TABLES
    print(f"About to DISABLE RLS on: {', '.join(tables)}")
    ans = input("Type 'yes' to confirm: ")
    if ans.strip().lower() != "yes":
        print("Aborted.")
        sys.exit(0)
    rollback_rls(tables)


if __name__ == "__main__":
    main()
