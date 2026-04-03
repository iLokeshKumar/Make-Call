"""
Migration: Interaction + LatencyLog schema v2
Adds: session_id, source, status, ended_at to Interaction
Adds: lead_id to LatencyLog

Run once from backend directory:
    python db_crud_operation/migrate_interaction_latency_v2.py
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

def run():
    with engine.connect() as conn:

        # ── Interaction table ──────────────────────────────────────────────────
        print("Migrating interaction table...")

        conn.execute(text("""
            ALTER TABLE interaction
            ADD COLUMN IF NOT EXISTS session_id VARCHAR;
        """))
        print("  ✅ session_id added (interaction)")

        conn.execute(text("""
            ALTER TABLE interaction
            ADD COLUMN IF NOT EXISTS source VARCHAR;
        """))
        print("  ✅ source added (interaction)")

        conn.execute(text("""
            ALTER TABLE interaction
            ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active';
        """))
        print("  ✅ status added (interaction)")

        conn.execute(text("""
            ALTER TABLE interaction
            ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP WITH TIME ZONE;
        """))
        print("  ✅ ended_at added (interaction)")

        # Index for session_id lookups
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_interaction_session_id
            ON interaction(session_id);
        """))
        print("  ✅ index ix_interaction_session_id created")

        # ── LatencyLog table ───────────────────────────────────────────────────
        print("Migrating latencylog table...")

        conn.execute(text("""
            ALTER TABLE latencylog
            ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES lead(id);
        """))
        print("  ✅ lead_id added (latencylog)")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_latencylog_lead_id
            ON latencylog(lead_id);
        """))
        print("  ✅ index ix_latencylog_lead_id created")

        conn.commit()
        print("\n✅ Migration complete.")

if __name__ == "__main__":
    run()
