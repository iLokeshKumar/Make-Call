from database import engine
from sqlalchemy import text


def run():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS latencylog (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                user_id INTEGER REFERENCES users(id),
                lead_id INTEGER REFERENCES leads(id),
                interaction_id INTEGER REFERENCES interactions(id),
                engine VARCHAR(120),
                stt_ms NUMERIC(12, 2) DEFAULT 0,
                llm_ms NUMERIC(12, 2) DEFAULT 0,
                tts_ms NUMERIC(12, 2) DEFAULT 0,
                total_ms NUMERIC(12, 2) DEFAULT 0,
                stt_provider VARCHAR(80),
                stt_model VARCHAR(120),
                llm_provider VARCHAR(80),
                llm_model VARCHAR(120),
                tts_provider VARCHAR(80),
                tts_model VARCHAR(120),
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS login_history (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                user_id INTEGER REFERENCES users(id),
                email VARCHAR(255),
                event_type VARCHAR(50),
                success BOOLEAN DEFAULT TRUE,
                ip_address VARCHAR(64),
                user_agent TEXT,
                failure_reason TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_latencylog_interaction_id ON latencylog(interaction_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_login_history_user_id ON login_history(user_id)"))
        conn.commit()
        print("✅ latencylog and login_history tables created/verified.")


if __name__ == "__main__":
    run()
